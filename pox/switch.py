# -*- coding: utf-8 -*-
# Copyright 2012,2013 Colin Scott
# Copyright 2012,2013 James McCauley
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
A software OpenFlow switch
----------------------------
Um software OpenFlow switch
"""

"""
TODO
----
* Don't reply to HELLOs -- just send one on connect
* Pass raw OFP packet to rx handlers as well as parsed
* Once previous is done, use raw OFP for error data when appropriate
* Check self.features to see if various features/actions are enabled,
  and act appropriately if they're not (rather than just doing them).
* Virtual ports currently have no config/state, but probably should.
* Provide a way to rebuild, e.g., the action handler table when the
  features object is adjusted.
---------------------------------------------------------------------

Não responda a HELLOs - basta enviar um em connect
* Passar pacote OFP cru para rx manipuladores, bem como analisado
* Uma vez feito o anterior, use o OFP bruto para dados de erro quando apropriado
* Verifique self.features para ver se vários recursos / ações estão habilitados,
   E agir adequadamente se eles não são (em vez de apenas fazê-los).
* Portas virtuais atualmente não têm configuração / estado, mas provavelmente deve.
* Fornecer uma maneira de reconstruir, por exemplo, a tabela do manipulador de
   O objeto de recursos é ajustado.
"""


from pox.lib.util import assert_type, initHelper, dpid_to_str
from pox.lib.revent import Event, EventMixin
from pox.lib.recoco import Timer
from pox.openflow.libopenflow_01 import *
import pox.openflow.libopenflow_01 as of
from pox.openflow.util import make_type_to_unpacker_table
from pox.openflow.flow_table import FlowTable, TableEntry
from pox.lib.packet import *

import logging
import struct
import time


# Multicast address used for STP 802.1D
# Endereço de multicast usado para STP 802.1D
_STP_MAC = EthAddr('01:80:c2:00:00:00')


class DpPacketOut (Event):
  #"Evento gerado quando um pacote de pacote de dados é enviado para fora de uma porta"
  """
  Event raised when a dataplane packet is sent out a port
  """
  def __init__ (self, node, packet, port):
    assert assert_type("packet", packet, ethernet, none_ok=False)
    Event.__init__(self)
    self.node = node
    self.packet = packet
    self.port = port
    self.switch = node # For backwards compatability


class SoftwareSwitchBase (object):
  #"Base do software do switch"
  def __init__ (self, dpid, name=None, ports=4, miss_send_len=128,
                max_buffers=100, max_entries=0x7fFFffFF, features=None):
    """
    Initialize switch
     - ports is a list of ofp_phy_ports or a number of ports
     - miss_send_len is number of bytes to send to controller on table miss
     - max_buffers is number of buffered packets to store
     - max_entries is max flows entries per table
    ------------------------------------------------------------------------
    Inicializar a chave
      - ports é uma lista de ofp_phy_ports ou um número de portas
      - miss_send_len é o número de bytes para enviar ao controlador na tabela miss
      - max_buffers é o número de pacotes armazenados em buffer para armazenar
      - max_entries é fluxo máximo de entradas por tabela
    """
    if name is None: name = dpid_to_str(dpid)
    self.name = name

    self.dpid = dpid

    if isinstance(ports, int):
      ports = [self.generate_port(i) for i in range(1, ports+1)]

    self.max_buffers = max_buffers
    self.max_entries = max_entries
    self.miss_send_len = miss_send_len
    self.config_flags = 0
    self._has_sent_hello = False

    self.table = FlowTable()
    self.table.addListeners(self)

    self._lookup_count = 0
    self._matched_count = 0

    self.log = logging.getLogger(self.name)
    self._connection = None

    # buffer for packets during packet_in
    # Buffer para pacotes durante packet_in
    self._packet_buffer = []

    # Map port_no -> openflow.pylibopenflow_01.ofp_phy_ports
    # Mapa port_no -> openflow.pylibopenflow_01.ofp_phy_ports
    self.ports = {}
    self.port_stats = {}

    for port in ports:
      self.add_port(port)

    if features is not None:
      self.features = features
    else:
      # Set up default features
      # Configurar recursos padrão

      self.features = SwitchFeatures()
      self.features.cap_flow_stats = True # Características  das estatísticas de fluxo
      self.features.cap_table_stats = True # Características  das estatísticas de tabela
      self.features.cap_port_stats = True # Características  das estatísticas de porta
      #self.features.cap_stp = True
      #self.features.cap_ip_reasm = True
      #self.features.cap_queue_stats = True
      #self.features.cap_arp_match_ip = True

      self.features.act_output = True # Características das ações de saída
      self.features.act_enqueue = True # Características das ações de colocação
      self.features.act_strip_vlan = True # Características das ações de vlan
      self.features.act_set_vlan_vid = True # Características das ações de vlan vid
      self.features.act_set_vlan_pcp = True # Características das ações de vlan pcp
      self.features.act_set_dl_dst = True #  Características das ações de endereço de destino Ethernet
      self.features.act_set_dl_src = True # Características das ações de endereço de origem Ethernet
      self.features.act_set_nw_dst = True #  Características das ações de endereço IP de destino 
      self.features.act_set_nw_src = True #  Características das ações de endereço IP de origem 
      self.features.act_set_nw_tos = True 
      self.features.act_set_tp_dst = True #  Características das ações de porta de destino TCP/UDP
      self.features.act_set_tp_src = True #  Características das ações de porta de origem TCP/UDP
      #self.features.act_vendor = True

    # Set up handlers for incoming OpenFlow messages
    # That is, self.ofp_handlers[OFPT_FOO] = self._rx_foo
    """
    Configurar manipuladores para mensagens OpenFlow recebidas
     Ou seja, self.ofp_handlers [OFPT_FOO] = self._rx_foo
    """
    self.ofp_handlers = {}
    for value,name in ofp_type_map.iteritems():
      name = name.split("OFPT_",1)[-1].lower()
      h = getattr(self, "_rx_" + name, None)
      if not h: continue
      assert of._message_type_to_class[value]._from_controller, name
      self.ofp_handlers[value] = h

    # Set up handlers for actions
    # That is, self.action_handlers[OFPAT_FOO] = self._action_foo
    #TODO: Refactor this with above
    """
    Configurar manipuladores para ações
     # Isso é, self.action_handlers [OFPAT_FOO] = self._action_foo
     #TODO: Refatorar isso com acima
    """
    self.action_handlers = {}
    for value,name in ofp_action_type_map.iteritems():
      name = name.split("OFPAT_",1)[-1].lower()
      h = getattr(self, "_action_" + name, None)
      if not h: continue
      if getattr(self.features, "act_" + name) is False: continue
      self.action_handlers[value] = h

    # Set up handlers for stats handlers
    # That is, self.stats_handlers[OFPST_FOO] = self._stats_foo
    #TODO: Refactor this with above
    """
    Configurar manipuladores para manipuladores de estatísticas
     # Ou seja, self.stats_handlers [OFPST_FOO] = self._stats_foo
     #TODO: Refatorar isso com acima
    """
    self.stats_handlers = {}
    for value,name in ofp_stats_type_map.iteritems():
      name = name.split("OFPST_",1)[-1].lower()
      h = getattr(self, "_stats_" + name, None)
      if not h: continue
      self.stats_handlers[value] = h

    # Set up handlers for flow mod handlers
    # That is, self.flow_mod_handlers[OFPFC_FOO] = self._flow_mod_foo
    #TODO: Refactor this with above
    """
    Configurar manipuladores para manipuladores de fluxo mod
     # Isso é, self.flow_mod_handlers [OFPFC_FOO] = self._flow_mod_foo
     #TODO: Refatorar isso com acima
    """
    self.flow_mod_handlers = {}
    for name,value in ofp_flow_mod_command_rev_map.iteritems():
      name = name.split("OFPFC_",1)[-1].lower()
      h = getattr(self, "_flow_mod_" + name, None)
      if not h: continue
      self.flow_mod_handlers[value] = h

  
  def _gen_port_name (self, port_no):
    #"Define nome da porta"
    return "%s.%s"%(dpid_to_str(self.dpid, True).replace('-','')[:12], port_no)

  
  def _gen_ethaddr (self, port_no):
    #"Define endereço ethernet"
    return EthAddr("02%06x%04x" % (self.dpid % 0x00FFff, port_no % 0xffFF))

  
  def generate_port (self, port_no, name = None, ethaddr = None):
    #"Define porta genérica"
    dpid = self.dpid
    p = ofp_phy_port()
    p.port_no = port_no
    if ethaddr is None:
      p.hw_addr = self._gen_ethaddr(p.port_no)
    else:
      p.hw_addr = EthAddr(ethaddr)
    if name is None:
      p.name = self._gen_port_name(p.port_no)
    else:
      p.name = name
    # Fill in features sort of arbitrarily
    # Preencha recursos de forma arbitrária
    p.config = OFPPC_NO_STP # OFPPC_NO_STP: Desativar 802.1D spanning árvore na porta.
    p.curr = OFPPF_10MB_HD # OFPPF_10MB_HD: Suporte de taxa half-duplex de 10 Mb
    p.advertised = OFPPF_10MB_HD
    p.supported = OFPPF_10MB_HD
    p.peer = OFPPF_10MB_HD
    return p

  @property
  
  def _time (self):
    #"Define o tempo"
    """
    Get the current time

    This should be used for, e.g., calculating timeouts.  It currently isn't
    used everywhere it should be.

    Override this to change time behavior.
    -------------------------------------------------------------------------
    Obter a hora atual

     Isto deve ser utilizado para, por exemplo, calcular os tempos limite. Atualmente não é
     Usado em toda parte deve ser.

     Substitua isso para alterar o comportamento do tempo.
    """
    return time.time()

  
  def _handle_FlowTableModification (self, event):
    #"Define o lançamento para modificação da flow table"
    """
    Handle flow table modification events
    """
    # Currently, we only use this for sending flow_removed messages

    """
    Manipular eventos de modificação de tabela de fluxo
    Atualmente, só usamos isso para enviar mensagens flow_removed
    """
    if not event.removed: return

    if event.reason in (OFPRR_IDLE_TIMEOUT,OFPRR_HARD_TIMEOUT,OFPRR_DELETE):
      # These reasons may lead to a flow_removed
      # Essas razões podem levar a uma flow_removed
      count = 0
      for entry in event.removed:
        if entry.flags & OFPFF_SEND_FLOW_REM and not entry.flags & OFPFF_EMERG:
          # Flow wants removal notification -- send it
          # Flow quer notificação de remoção - envie-o
          fr = entry.to_flow_removed(self._time, reason=event.reason)
          self.send(fr)
          count += 1
      self.log.debug("%d flows removed (%d removal notifications)",
          len(event.removed), count)
  
  def rx_message (self, connection, msg):
    #"Define rx messagem"
    """
    Handle an incoming OpenFlow message
    -----------------------------------
    Lidar com uma mensagem OpenFlow de entrada
    """
    ofp_type = msg.header_type
    h = self.ofp_handlers.get(ofp_type)
    if h is None:
      raise RuntimeError("No handler for ofp_type %s(%d)" #Nenhum manipulador para ofp_type
                         % (ofp_type_map.get(ofp_type), ofp_type))

    self.log.debug("Got %s with XID %s",ofp_type_map.get(ofp_type),msg.xid)
    h(msg, connection=connection)

  
  def set_connection (self, connection):
    #"Define a conexão deste switch."
    """
    Set this switch's connection.
    """
    self._has_sent_hello = False
    connection.set_message_handler(self.rx_message)
    self._connection = connection

  
  def send (self, message, connection = None):
    #"Enviar uma mensagem para o parceiro de comunicação deste switch"
    """
    Send a message to this switch's communication partner
    """
    if connection is None:
      connection = self._connection
    if connection:
      connection.send(message)
    else:
      self.log.debug("Asked to send message %s, but not connected", message) #Asked to send message x, but not connected

  
  def _rx_hello (self, ofp, connection):
    #"Define rx hello"
    #FIXME: This isn't really how hello is supposed to work -- we're supposed
    #       to send it immediately on connection.  See _send_hello().
    """
    Isto não é realmente como olá é suposto para trabalhar - nós é suposto
     # Para enviá-lo imediatamente na conexão. Consulte _send_hello ().
    """
    self.send_hello()

  
  def _rx_echo_request (self, ofp, connection):
    #"Processa solicitações de eco"
    """
    Handles echo requests
    """
    msg = ofp_echo_reply(xid=ofp.xid, body=ofp.body)
    self.send(msg)

  
  def _rx_features_request (self, ofp, connection):
    #"Processa solicitações de recursos"
    """
    Handles feature requests
    """
    self.log.debug("Send features reply")
    #"A mensagem OFPT_FEATURES_REQUEST é usada pelo controlador para identificar o switch e ler suas capacidades básicas"
    msg = ofp_features_reply(datapath_id = self.dpid, #datapath_id: ID exclusivo Datapath. Os 48 bits mais baixos são para
                                                      #Um endereço MAC, enquanto os 16 bits superiores são Implementador-definido
                             xid = ofp.xid, 
                             n_buffers = self.max_buffers, #n_buffers: Máximo de pacotes armazenados simultaneamente.
                             n_tables = 1, #n_tables: Número de tabelas suportadas pelo datapath
                             capabilities = self.features.capability_bits, #Bitmap de suporte "ofp_capabilities".
                             actions = self.features.action_bits,
                             ports = self.ports.values())
    self.send(msg)

  
  def _rx_flow_mod (self, ofp, connection):
    #"Manipula mods de fluxo"
    """
    Handles flow mods
    """
    self.log.debug("Flow mod details: %s", ofp.show())

    #self.table.process_flow_mod(ofp)
    #self._process_flow_mod(ofp, connection=connection, table=self.table)
    handler = self.flow_mod_handlers.get(ofp.command)
    if handler is None:
      self.log.warn("Command not implemented: %s" % command)
      #OFPET_FLOW_MOD_FAILED: Problema ao modificar entrada de fluxo
      #OFPFMFC_BAD_COMMAND: Comando não suportado ou desconhecido
      self.send_error(type=OFPET_FLOW_MOD_FAILED, code=OFPFMFC_BAD_COMMAND,
                      ofp=ofp, connection=connection)
      return
    handler(flow_mod=ofp, connection=connection, table=self.table)

    if ofp.buffer_id is not None:
      self._process_actions_for_packet_from_buffer(ofp.actions, ofp.buffer_id,
                                                   ofp)

  
  def _rx_packet_out (self, packet_out, connection):
    #"Manipula pacotes de saída"
    """
    Handles packet_outs
    """
    self.log.debug("Packet out details: %s", packet_out.show())

    if packet_out.data:
      self._process_actions_for_packet(packet_out.actions, packet_out.data,
                                       packet_out.in_port, packet_out)
    elif packet_out.buffer_id is not None:
      self._process_actions_for_packet_from_buffer(packet_out.actions,
                                                   packet_out.buffer_id,
                                                   packet_out)
    else:
      self.log.warn("packet_out: No data and no buffer_id -- "
                    "don't know what to send")

  
  def _rx_echo_reply (self, ofp, connection):
    #"Mensagem de resposta"
    pass

  
  def _rx_barrier_request (self, ofp, connection):
    #"Pedido de barreira"
    msg = ofp_barrier_reply(xid = ofp.xid)
    self.send(msg)

  
  def _rx_get_config_request (self, ofp, connection):
    #"Configuração de requisição"
    msg = ofp_get_config_reply(xid = ofp.xid)
    msg.miss_send_len = self.miss_send_len
    msg.flags = self.config_flags
    self.log.debug("Sending switch config reply %s", msg)
    self.send(msg)

  
  def _rx_stats_request (self, ofp, connection):
    #"Define as estatísticas da requisição"
    handler = self.stats_handlers.get(ofp.type)
    if handler is None:
      self.log.warning("Stats type %s not implemented", ofp.type)

      self.send_error(type=OFPET_BAD_REQUEST, code=OFPBRC_BAD_STAT,
                      ofp=ofp, connection=connection)
      return

    body = handler(ofp, connection=connection)
    if body is not None:
      reply = ofp_stats_reply(xid=ofp.xid, type=ofp.type, body=body)
      self.log.debug("Sending stats reply %s", reply)
      self.send(reply)

  
  def _rx_set_config (self, config, connection):
    #"Estabelece configuração"
    self.miss_send_len = config.miss_send_len
    self.config_flags = config.flags

  
  def _rx_port_mod (self, port_mod, connection):
    #"Define modificação de porta"
    port_no = port_mod.port_no
    if port_no not in self.ports:
      #OFPET_PORT_MOD_FAILED: Falha na solicitação de modificação de porta
      #OFPPMFC_BAD_PORT: O número de porta especificada não existe
      self.send_error(type=OFPET_PORT_MOD_FAILED, code=OFPPMFC_BAD_PORT,
                      ofp=port_mod, connection=connection)
      return
    port = self.ports[port_no]
    if port.hw_addr != port_mod.hw_addr:
      #OFPET_PORT_MOD_FAILED: Falha na solicitação de modificação de porta
      #OFPPMFC_BAD_HW_ADDR: O endereço de hardware especificado não corresponde ao número da porta
      self.send_error(type=OFPET_PORT_MOD_FAILED, code=OFPPMFC_BAD_HW_ADDR,
                      ofp=port_mod, connection=connection)
      return

    mask = port_mod.mask

    for bit in range(32):
      bit = 1 << bit
      if mask & bit:
        handled,r = self._set_port_config_bit(port, bit, port_mod.config & bit)
        if not handled:
          self.log.warn("Unsupported port config flag: %08x", bit)
          continue
        if r is not None:
          msg = "Port %s: " % (port.port_no,)
          if isinstance(r, str):
            msg += r
          else:
            msg += ofp_port_config_map.get(bit, "config bit %x" % (bit,))
            msg += " set to "
            msg += "true" if r else "false"
          self.log.debug(msg)

  
  def _rx_vendor (self, vendor, connection):
    #"Define vendor"
    # We don't support vendor extensions, so send an OFP_ERROR, per
    # page 42 of spec
    """
    Nós não suportamos extensões de fornecedores, então envie um OFP_ERROR, por
      Página 42 de especificações
    """
    self.send_error(type=OFPET_BAD_REQUEST, code=OFPBRC_BAD_VENDOR,
                    ofp=vendor, connection=connection)

  
  def _rx_queue_get_config_request (self, ofp, connection):
    #"Processa uma mensagem OFPT_QUEUE_GET_CONFIG_REQUEST."
    """
    Handles an OFPT_QUEUE_GET_CONFIG_REQUEST message.
    """
    reply = ofp_queue_get_config_reply(xid=ofp.xid, port=ofp.port, queues=[])
    self.log.debug("Sending queue get config reply %s", reply)
    self.send(reply)

  
  def send_hello (self, force = False):
    #"Enviar Olá (uma vez)"
    """
    Send hello (once)
    """
    #FIXME: This is wrong -- we should just send when connecting.
    #Isso é errado - devemos apenas enviar ao conectar.
    if self._has_sent_hello and not force: return
    self._has_sent_hello = True
    self.log.debug("Sent hello")
    msg = ofp_hello(xid=0)
    self.send(msg)

  
  def send_packet_in (self, in_port, buffer_id=None, packet=b'', reason=None,
                      data_length=None):
    #"Enviar pacote de entrada"
    """
    Send PacketIn
    """
    if hasattr(packet, 'pack'):
      packet = packet.pack()
    assert assert_type("packet", packet, bytes)
    self.log.debug("Send PacketIn")
    if reason is None:
      reason = OFPR_NO_MATCH
    if data_length is not None and len(packet) > data_length:
      if buffer_id is not None:
        packet = packet[:data_length]

    msg = ofp_packet_in(xid = 0, in_port = in_port, buffer_id = buffer_id,
                        reason = reason, data = packet)

    self.send(msg)

  
  def send_port_status (self, port, reason):
    #"Estado da porta de envio"
    """
    Send port status

    port is an ofp_phy_port
    reason is one of OFPPR_xxx
    --------------------------
     Porta é um ofp_phy_port
     Razão é uma das OFPPR_xxx
    """
    assert assert_type("port", port, ofp_phy_port, none_ok=False)
    assert reason in ofp_port_reason_rev_map.values()
    msg = ofp_port_status(desc=port, reason=reason)
    self.send(msg)

  
  def send_error (self, type, code, ofp=None, data=None, connection=None):
    #"Enviar um erro"
    """
    Send an error

    If you pass ofp, it will be used as the source of the error's XID and
    data.
    You can override the data by also specifying data.
    ----------------------------------------------------------------------
    Se você passar de p, ele será usado como a fonte do XID do erro e
     dados.
     Você pode substituir os dados também especificando dados.
    """
    err = ofp_error(type=type, code=code)
    if ofp:
      err.xid = ofp.xid
      err.data = ofp.pack()
    else:
      err.xid = 0
    if data is not None:
      err.data = data
    self.send(err, connection = connection)

  
  def rx_packet (self, packet, in_port, packet_data = None):
    #"Processar um pacote de dados"
    """
    process a dataplane packet

    packet: an instance of ethernet
    in_port: the integer port number
    packet_data: packed version of packet if available
    --------------------------------------------------
    Pacote: uma instância de ethernet
     In_port: o número de porta inteiro
     Packet_data: versão pacote do pacote se disponível
    """
    assert assert_type("packet", packet, ethernet, none_ok=False)
    assert assert_type("in_port", in_port, int, none_ok=False)
    port = self.ports.get(in_port)
    if port is None:
      self.log.warn("Got packet on missing port %i", in_port)
      return

    is_stp = packet.dst == _STP_MAC

    if (port.config & OFPPC_NO_RECV) and not is_stp:
      # Drop all except STP
      #Eliminar tudo, exceto STP
      return
    if (port.config & OFPPC_NO_RECV_STP) and is_stp:
      # Drop STP
      #Apaga STP
      return

    if self.config_flags & OFPC_FRAG_MASK:
      ipp = packet.find(ipv4)
      if ipp:
        if (ipp.flags & ipv4.MF_FLAG) or ipp.frag != 0:
          frag_mode = self.config_flags & OFPC_FRAG_MASK
          if frag_mode == OFPC_FRAG_DROP:
            # Drop fragment
            # Apaga fragmento
            return
          elif frag_mode == OFPC_FRAG_REASM:
            if self.features.cap_ip_reasm:
              #TODO: Implement fragment reassembly
              #Implementar remontagem de fragmentos
              self.log.info("Can't reassemble fragment: not implemented") #Não é possível remontar fragmento: não implementado
          else:
            self.log.warn("Illegal fragment processing mode: %i", frag_mode) #Modo de processamento de fragmento ilegal

    self.port_stats[in_port].rx_packets += 1
    if packet_data is not None:
      self.port_stats[in_port].rx_bytes += len(packet_data)
    else:
      self.port_stats[in_port].rx_bytes += len(packet.pack()) # Expensive

    self._lookup_count += 1
    entry = self.table.entry_for_packet(packet, in_port)
    if entry is not None:
      self._matched_count += 1
      entry.touch_packet(len(packet))
      self._process_actions_for_packet(entry.actions, packet, in_port)
    else:
      # no matching entry
      # Nenhuma entrada correspondente
      if port.config & OFPPC_NO_PACKET_IN:
        return
      buffer_id = self._buffer_packet(packet, in_port)
      if packet_data is None:
        packet_data = packet.pack()
      self.send_packet_in(in_port, buffer_id, packet_data,
                          reason=OFPR_NO_MATCH, data_length=self.miss_send_len)

  
  def delete_port (self, port):
    #"Remove uma porta"
    """
    Removes a port

    Sends a port_status message to the controller

    Returns the removed phy_port
    ---------------------------------------------
    Envia uma mensagem port_status para o controlador

     Retorna o phy_port removido
    """
    try:
      port_no = port.port_no
      assert self.ports[port_no] is port
    except:
      port_no = port
      port = self.ports[port_no]
    if port_no not in self.ports:
      raise RuntimeError("Can't remove nonexistent port " + str(port_no)) #Não é possível remover a porta inexistente
    self.send_port_status(port, OFPPR_DELETE)
    del self.ports[port_no]
    return port

  
  def add_port (self, port):
    #"Acrescenta uma porta"
    """
    Adds a port

    Sends a port_status message to the controller
    ----------------------------------------------
    Envia uma mensagem port_status para o controlador
    """
    try:
      port_no = port.port_no
    except:
      port_no = port
      port = self.generate_port(port_no, self.dpid)
    if port_no in self.ports:
      raise RuntimeError("Port %s already exists" % (port_no,)) #Porta x já existe
    self.ports[port_no] = port
    self.port_stats[port.port_no] = ofp_port_stats(port_no=port.port_no)
    self.send_port_status(port, OFPPR_ADD)

  
  def _set_port_config_bit (self, port, bit, value):
    #"Definir um bit de configuração de porta"
    """
    Set a port config bit

    This is called in response to port_mods.  It is passed the ofp_phy_port,
    the bit/mask, and the value of the bit (i.e., 0 if the flag is to be
    unset, or the same value as bit if it is to be set).

    The return value is a tuple (handled, msg).
    If bit is handled, then handled will be True, else False.
    if msg is a string, it will be used as part of a log message.
    If msg is None, there will be no log message.
    If msg is anything else "truthy", an "enabled" log message is generated.
    If msg is anything else "falsy", a "disabled" log message is generated.
    msg is only used when handled is True.
    -----------------------------------------------------------------------
     Isso é chamado em resposta a port_mods. É passado o ofp_phy_port,
     O bit / máscara, eo valor do bit (isto é, 0 se o sinalizador deve ser
     Unset, ou o mesmo valor como bit se for para ser definido).

     O valor de retorno é uma tupla (manipulada, msg).
     Se o bit é tratado, então manipulado será True, senão False.
     Se msg é uma string, ela será usada como parte de uma mensagem de log.
     Se msg for Nenhum, não haverá nenhuma mensagem de log.
     Se msg é qualquer outra coisa "truthy", uma mensagem de log "enabled" é gerada.
     Se msg é qualquer outra coisa "falsy", uma mensagem de log "disabled" é gerada.
     Msg é usado somente quando manipulado é True.
    """
    if bit == OFPPC_NO_STP:
      if value == 0:
        # we also might send OFPBRC_EPERM if trying to disable this bit
        # Também podemos enviar OFPBRC_EPERM se tentar desativar este bit
        self.log.warn("Port %s: Can't enable 802.1D STP", port.port_no)
      return (True, None)

    """
    OFPPC_PORT_DOWN: Porta está administrativamente down.
    OFPPC_NO_STP: Desativar 802.1D spanning árvore na porta
    OFPPC_NO_RECV: Apagar a maioria dos pacotes recebidos na porta
    OFPPC_NO_RECV_STP: Apagar pacotes 802.1D STP recebidos  
    OFPPC_NO_FLOOD: Não inclua esta porta quando inundar
    OFPPC_NO_FWD: Apagar pacotes encaminhados para a porta
    OFPPC_NO_PACKET_IN: Não envie msgs de pacotes para a porta
    """
    if bit not in (OFPPC_PORT_DOWN, OFPPC_NO_STP, OFPPC_NO_RECV, OFPPC_NO_RECV_STP,
                   OFPPC_NO_FLOOD, OFPPC_NO_FWD, OFPPC_NO_PACKET_IN):
      return (False, None)

    if port.set_config(value, bit):
      if bit == OFPPC_PORT_DOWN:
        # Note (Peter Peresini): Although the spec is not clear about it,
        # we will assume that config.OFPPC_PORT_DOWN implies
        # state.OFPPS_LINK_DOWN. This is consistent with Open vSwitch.

        #TODO: for now, we assume that there is always physical link present
        # and that the link state depends only on the configuration.
        #---------------------------------------------------------------------
        """
        Nota (Peter Peresini): Embora a especificação não é clara sobre isso,
         # Assumiremos que config.OFPPC_PORT_DOWN implica
         # State.OFPPS_LINK_DOWN. Isso é consistente com Open vSwitch.

         #TODO: por agora, presumimos que existe sempre link físico presente
         # E que o estado do link depende apenas da configuração.
        """
        old_state = port.state & OFPPS_LINK_DOWN # Nenhuma ligação física presente
        port.state = port.state & ~OFPPS_LINK_DOWN
        if port.config & OFPPC_PORT_DOWN:
          port.state = port.state | OFPPS_LINK_DOWN
        new_state = port.state & OFPPS_LINK_DOWN
        if old_state != new_state:
          self.send_port_status(port, OFPPR_MODIFY)

      # Do default log message.
      #Fazer mensagem de log padrão.
      return (True, value)

    # No change -- no log message.
    # Nenhuma alteração - nenhuma mensagem de log.
    return (True, None)

  
  def _output_packet_physical (self, packet, port_no):
    #"Enviar um pacote para fora uma única porta física"
    """
    send a packet out a single physical port

    This is called by the more general _output_packet().

    Override this.
    -----------------------------------------------------
    Isso é chamado pelo mais geral _output_packet ().

     Substitua isso.
    """
    self.log.info("Sending packet %s out port %s", str(packet), port_no)

  
  def _output_packet (self, packet, out_port, in_port, max_len=None):
    #"Enviar um pacote para fora alguma porta"
    """
    send a packet out some port

    This handles virtual ports and does validation.

    packet: instance of ethernet
    out_port, in_port: the integer port number
    max_len: maximum packet payload length to send to controller
    --------------------------------------------------------------
    Isso manipula portas virtuais e faz validação.

     Pacote: instância de ethernet
     Out_port, in_port: o número de porta inteiro
     Max_len: comprimento máximo da carga útil do pacote para enviar ao controlador
    """
    assert assert_type("packet", packet, ethernet, none_ok=False)

    
    def real_send (port_no, allow_in_port=False):
      #"Envio real"
      if type(port_no) == ofp_phy_port:
        port_no = port_no.port_no
      if port_no == in_port and not allow_in_port:
        self.log.warn("Dropping packet sent on port %i: Input port", port_no) # Apagar pacote enviado na porta x: Porta de entrada 
        return
      if port_no not in self.ports:
        self.log.warn("Dropping packet sent on port %i: Invalid port", port_no) # Apagar pacote enviado na porta x: Porta inválida 
        return
      if self.ports[port_no].config & OFPPC_NO_FWD:
        self.log.warn("Dropping packet sent on port %i: Forwarding disabled", # Apagar pacote enviado na porta x: Encaminhamento desativado
                      port_no)
        return
      if self.ports[port_no].config & OFPPC_PORT_DOWN:
        self.log.warn("Dropping packet sent on port %i: Port down", port_no) # Apagar pacote enviado na porta x: Porta para baixo
        return
      if self.ports[port_no].state & OFPPS_LINK_DOWN:
        self.log.debug("Dropping packet sent on port %i: Link down", port_no) # Apagar pacote enviado na porta x: Link para baixo
        return
      self.port_stats[port_no].tx_packets += 1
      self.port_stats[port_no].tx_bytes += len(packet.pack()) #FIXME: Expensive
      self._output_packet_physical(packet, port_no)

    if out_port < OFPP_MAX:
      real_send(out_port)
    elif out_port == OFPP_IN_PORT:
      real_send(in_port, allow_in_port=True)
    elif out_port == OFPP_FLOOD:
      for no,port in self.ports.iteritems():
        if no == in_port: continue
        if port.config & OFPPC_NO_FLOOD: continue
        real_send(port)
    elif out_port == OFPP_ALL:
      for no,port in self.ports.iteritems():
        if no == in_port: continue
        real_send(port)
    elif out_port == OFPP_CONTROLLER:
      buffer_id = self._buffer_packet(packet, in_port)
      # Should we honor OFPPC_NO_PACKET_IN here?
      # Devemos honrar OFPPC_NO_PACKET_IN aqui?
      self.send_packet_in(in_port, buffer_id, packet, reason=OFPR_ACTION,
                          data_length=max_len)
    elif out_port == OFPP_TABLE:
      # Do we disable send-to-controller when performing this?
      # (Currently, there's the possibility that a table miss from this
      # will result in a send-to-controller which may send back to table...)
      #------------------------------------------------------------------------------------
      """
      Podemos desativar enviar-para-controlador ao executar isso?
       # (Atualmente, existe a possibilidade de que uma tabela não
       # Resultará em um envio para controlador que pode enviar de volta para a tabela ...)
      """
      self.rx_packet(packet, in_port)
    else:
      self.log.warn("Unsupported virtual output port: %d", out_port) # Porta de saída virtual não suportada

  
  def _buffer_packet (self, packet, in_port=None):
    #"Faz o buffer do pacote e retorna buffer ID"
    """
    Buffer packet and return buffer ID

    If no buffer is available, return None.
    --------------------------------------
    Se nenhum buffer estiver disponível, retornar Nenhum.
    """
    # Do we have an empty slot?
    # Temos um slot vazio?
    for (i, value) in enumerate(self._packet_buffer):
      if value is None:
        # Yes -- use it
        # Sim, usamos ele
        self._packet_buffer[i] = (packet, in_port)
        return i + 1
    # No -- create a new slow
    #Nao, cria um novo slot
    if len(self._packet_buffer) >= self.max_buffers:
      # No buffers available!
      # Sem buffers disponíveis
      return None
    self._packet_buffer.append( (packet, in_port) )
    return len(self._packet_buffer)

  
  def _process_actions_for_packet_from_buffer (self, actions, buffer_id,
                                               ofp=None):
    #"Saída e liberar um pacote do buffer"
    """
    output and release a packet from the buffer

    ofp is the message which triggered this processing, if any (used for error
    generation)
    --------------------------------------------------------------------------
    Ofp é a mensagem que acionou esse processamento, se houver (usado para erro
     geração)
    """
    buffer_id = buffer_id - 1
    if (buffer_id >= len(self._packet_buffer)) or (buffer_id < 0):
      self.log.warn("Invalid output buffer id: %d", buffer_id + 1) # ID do buffer de saída inválido
      return
    if self._packet_buffer[buffer_id] is None:
      self.log.warn("Buffer %d has already been flushed", buffer_id + 1) #Buffer já foi liberado
      return
    (packet, in_port) = self._packet_buffer[buffer_id]
    self._process_actions_for_packet(actions, packet, in_port, ofp)
    self._packet_buffer[buffer_id] = None

  
  def _process_actions_for_packet (self, actions, packet, in_port, ofp=None):
    #"Processar as ações de saída para um pacote"
    """
    process the output actions for a packet

    ofp is the message which triggered this processing, if any (used for error
    generation)
    ----------------------------------------------------------------------------
    Ofp é a mensagem que acionou esse processamento, se houver (usado para erro
     geração)
    """
    assert assert_type("packet", packet, (ethernet, bytes), none_ok=False)
    if not isinstance(packet, ethernet):
      packet = ethernet.unpack(packet)

    for action in actions:
      #if action.type is ofp_action_resubmit:
      #  self.rx_packet(packet, in_port)
      #  return
      h = self.action_handlers.get(action.type)
      if h is None:
        self.log.warn("Unknown action type: %x " % (action.type,))
        self.send_error(type=OFPET_BAD_ACTION, code=OFPBAC_BAD_TYPE, ofp=ofp)
        return
      packet = h(action, packet, in_port)

  
  def _flow_mod_add (self, flow_mod, connection, table):
    #"Processar um mod de fluxo OFPFC_ADD enviado para o switch."
    """
    Process an OFPFC_ADD flow mod sent to the switch.
    """
    match = flow_mod.match
    priority = flow_mod.priority

    if flow_mod.flags & OFPFF_EMERG:
      if flow_mod.idle_timeout != 0 or flow_mod.hard_timeout != 0:
        # Emergency flow mod has non-zero timeouts. Do not add.
        # A modificação de fluxo de emergência tem tempos de espera não nulos. Não adicione.
        self.log.warn("Rejecting emergency flow with nonzero timeout") # Rejeitando fluxo de emergência com tempo limite não nulo
        self.send_error(type=OFPET_FLOW_MOD_FAILED,
                        code=OFPFMFC_BAD_EMERG_TIMEOUT,
                        ofp=flow_mod, connection=connection)
        return
      if flow_mod.flags & OFPFF_SEND_FLOW_REM:
        # Emergency flows can't send removal messages, we we might want to
        # reject this early.  Sadly, there's no error code for this, so we just
        # abuse EPERM.  If we eventually support Nicira extended error codes,
        # we should use one here.
        #------------------------------------------------------------------------------------
        """
        Os fluxos de emergência não podem enviar mensagens de remoção, nós
         # Rejeitar isso cedo. Infelizmente, não há código de erro para isso, então nós apenas
         # Abuso EPERM. Se nós finalmente apoiar Nicira estendido códigos de erro,
         # Devemos usar um aqui.
        """
        self.log.warn("Rejecting emergency flow with flow removal flag") # Rejeição do fluxo de emergência com indicador de remoção de fluxo
        self.send_error(type=OFPET_FLOW_MOD_FAILED,
                        code=OFPFMFC_EPERM,
                        ofp=flow_mod, connection=connection)
        return
      #NOTE: An error is sent anyways because the current implementation does
      #      not support emergency entries.
      """
      Um erro é enviado de qualquer maneira porque a implementação atual não
       # Não suporta entradas de emergência.
      """
      self.log.warn("Rejecting emergency flow (not supported)") # Rejeitando o fluxo de emergência (não suportado)
      self.send_error(type=OFPET_FLOW_MOD_FAILED,
                      code=OFPFMFC_ALL_TABLES_FULL,
                      ofp=flow_mod, connection=connection)
      return

    new_entry = TableEntry.from_flow_mod(flow_mod)

    if flow_mod.flags & OFPFF_CHECK_OVERLAP:
      if table.check_for_overlapping_entry(new_entry):
        # Another entry overlaps. Do not add.
        # Outra entrada sobrepõe-se. Não adicione.
        self.send_error(type=OFPET_FLOW_MOD_FAILED, code=OFPFMFC_OVERLAP,
                        ofp=flow_mod, connection=connection)
        return

    if flow_mod.command == OFPFC_ADD:
      # Exactly matching entries have to be removed if OFPFC_ADD
      # As entradas  correspondentes precisam ser removidas se OFPFC_ADD
      table.remove_matching_entries(match, priority=priority, strict=True)

    if len(table) >= self.max_entries:
      # Flow table is full. Respond with error message.
      # A tabela de fluxo está cheia. Responder com mensagem de erro.
      self.send_error(type=OFPET_FLOW_MOD_FAILED,
                      code=OFPFMFC_ALL_TABLES_FULL,
                      ofp=flow_mod, connection=connection)
      return

    table.add_entry(new_entry)

  
  def _flow_mod_modify (self, flow_mod, connection, table, strict=False):
    #"Processar um mod de fluxo OFPFC_MODIFY enviado para o switch."
    """
    Process an OFPFC_MODIFY flow mod sent to the switch.
    """
    match = flow_mod.match
    priority = flow_mod.priority

    modified = False
    for entry in table.entries:
      # update the actions field in the matching flows
      # Atualizar o campo de ações nos fluxos correspondentes
      if entry.is_matched_by(match, priority=priority, strict=strict):
        entry.actions = flow_mod.actions
        modified = True

    if not modified:
      # if no matching entry is found, modify acts as add
      # Se nenhuma entrada correspondente for encontrada, modifique age como add
      self._flow_mod_add(flow_mod, connection, table)

  
  def _flow_mod_modify_strict (self, flow_mod, connection, table):
    #"Processar um mod de fluxo OFPFC_MODIFY_STRICT enviado para o switch."
    """
    Process an OFPFC_MODIFY_STRICT flow mod sent to the switch.
    """
    self._flow_mod_modify(flow_mod, connection, table, strict=True)

  
  def _flow_mod_delete (self, flow_mod, connection, table, strict=False):
    #"Processar um fluxo OFPFC_DELETE mod enviado para o switch."
    """
    Process an OFPFC_DELETE flow mod sent to the switch.
    """
    match = flow_mod.match
    priority = flow_mod.priority

    out_port = flow_mod.out_port
    if out_port == OFPP_NONE: out_port = None # Don't filter
    table.remove_matching_entries(match, priority=priority, strict=strict,
                                  out_port=out_port, reason=OFPRR_DELETE)

  
  def _flow_mod_delete_strict (self, flow_mod, connection, table):
    #"Processar um mod de fluxo OFPFC_DELETE_STRICT enviado para o switch."
    """
    Process an OFPFC_DELETE_STRICT flow mod sent to the switch.
    """
    self._flow_mod_delete(flow_mod, connection, table, strict=True)

  
  def _action_output (self, action, packet, in_port):
    #"Define ação de saída"
    self._output_packet(packet, action.port, in_port, action.max_len)
    return packet

  
  def _action_set_vlan_vid (self, action, packet, in_port):
    #"Estabele ações da vlan_vid"
    if not isinstance(packet.payload, vlan):
      vl = vlan()
      vl.eth_type = packet.type
      vl.payload = packet.payload
      packet.type = ethernet.VLAN_TYPE
      packet.payload = vl
    packet.payload.id = action.vlan_vid
    return packet

  
  def _action_set_vlan_pcp (self, action, packet, in_port):
    #"Estabelece ação vlan_pcp"
    if not isinstance(packet.payload, vlan):
      vl = vlan()
      vl.payload = packet.payload
      vl.eth_type = packet.type
      packet.payload = vl
      packet.type = ethernet.VLAN_TYPE
    packet.payload.pcp = action.vlan_pcp
    return packet

  
  def _action_strip_vlan (self, action, packet, in_port):
    #"Ação de vlan"
    if isinstance(packet.payload, vlan):
      packet.type = packet.payload.eth_type
      packet.payload = packet.payload.payload
    return packet

  
  def _action_set_dl_src (self, action, packet, in_port):
    #"Estabelece ação do Endereço de origem Ethernet."
    packet.src = action.dl_addr
    return packet

  
  def _action_set_dl_dst (self, action, packet, in_port):
    #"Estabelece ação do Endereço de destino Ethernet."
    packet.dst = action.dl_addr
    return packet

  
  def _action_set_nw_src (self, action, packet, in_port):
    #"Estabelece IP de origem"
    nw = packet.payload
    if isinstance(nw, vlan):
      nw = nw.payload
    if isinstance(nw, ipv4):
      nw.srcip = action.nw_addr
    return packet

  
  def _action_set_nw_dst (self, action, packet, in_port):
    #"Estabelece IP de destino"
    nw = packet.payload
    if isinstance(nw, vlan):
      nw = nw.payload
    if isinstance(nw, ipv4):
      nw.dstip = action.nw_addr
    return packet

  
  def _action_set_nw_tos (self, action, packet, in_port):
    #"Estabelece IP"
    nw = packet.payload
    if isinstance(nw, vlan):
      nw = nw.payload
    if isinstance(nw, ipv4):
      nw.tos = action.nw_tos
    return packet

  
  def _action_set_tp_src (self, action, packet, in_port):
    #"Estabelece Porta de origem TCP / UDP"
    nw = packet.payload
    if isinstance(nw, vlan):
      nw = nw.payload
    if isinstance(nw, ipv4):
      tp = nw.payload
      if isinstance(tp, udp) or isinstance(tp, tcp):
        tp.srcport = action.tp_port
    return packet

  
  def _action_set_tp_dst (self, action, packet, in_port):
    #"Estabelece Porta de destino TCP / UDP"
    nw = packet.payload
    if isinstance(nw, vlan):
      nw = nw.payload
    if isinstance(nw, ipv4):
      tp = nw.payload
      if isinstance(tp, udp) or isinstance(tp, tcp):
        tp.dstport = action.tp_port
    return packet

  
  def _action_enqueue (self, action, packet, in_port):
    #"Ação de Enqueue"
    self.log.warn("Enqueue not supported.  Performing regular output.") # Enqueue não suportado. Executando saída regular
    self._output_packet(packet, action.tp_port, in_port)
    return packet
#  def _action_push_mpls_tag (self, action, packet, in_port):
#    bottom_of_stack = isinstance(packet.next, mpls)
#    packet.next = mpls(prev = packet.pack())
#    if bottom_of_stack:
#      packet.next.s = 1
#    packet.type = action.ethertype
#    return packet
#  def _action_pop_mpls_tag (self, action, packet, in_port):
#    if not isinstance(packet.next, mpls):
#      return packet
#    if not isinstance(packet.next.next, str):
#      packet.next.next = packet.next.next.pack()
#    if action.ethertype in ethernet.type_parsers:
#      packet.next = ethernet.type_parsers[action.ethertype](packet.next.next)
#    else:
#      packet.next = packet.next.next
#    packet.ethertype = action.ethertype
#    return packet
#  def _action_set_mpls_label (self, action, packet, in_port):
#    if not isinstance(packet.next, mpls):
#      mock = ofp_action_push_mpls()
#      packet = push_mpls_tag(mock, packet)
#    packet.next.label = action.mpls_label
#    return packet
#  def _action_set_mpls_tc (self, action, packet, in_port):
#    if not isinstance(packet.next, mpls):
#      mock = ofp_action_push_mpls()
#      packet = push_mpls_tag(mock, packet)
#    packet.next.tc = action.mpls_tc
#    return packet
#  def _action_set_mpls_ttl (self, action, packet, in_port):
#    if not isinstance(packet.next, mpls):
#      mock = ofp_action_push_mpls()
#      packet = push_mpls_tag(mock, packet)
#    packet.next.ttl = action.mpls_ttl
#    return packet
#  def _action_dec_mpls_ttl (self, action, packet, in_port):
#    if not isinstance(packet.next, mpls):
#      return packet
#    packet.next.ttl = packet.next.ttl - 1
#    return packet

  
  def _stats_desc (self, ofp, connection):
    #"Define as estatísticas do desc"
    try:
      from pox.core import core
      return ofp_desc_stats(mfr_desc="POX",
                            hw_desc=core._get_platform_info(),
                            sw_desc=core.version_string,
                            serial_num=str(self.dpid),
                            dp_desc=type(self).__name__)
    except:
      return ofp_desc_stats(mfr_desc="POX",
                            hw_desc="Unknown",
                            sw_desc="Unknown",
                            serial_num=str(self.dpid),
                            dp_desc=type(self).__name__)

  
  def _stats_flow (self, ofp, connection):
    #"Define estatísticas de fluxo"
    if ofp.body.table_id not in (TABLE_ALL, 0):
      return [] # No flows for other tables
    out_port = ofp.body.out_port
    if out_port == OFPP_NONE: out_port = None # Don't filter
    return self.table.flow_stats(ofp.body.match, out_port)

  
  def _stats_aggregate (self, ofp, connection):
    #"Define estatísticas agregadas"
    if ofp.body.table_id not in (TABLE_ALL, 0):
      return [] # No flows for other tables/ Sem fluxos para outras tabelas
    out_port = ofp.body.out_port
    if out_port == OFPP_NONE: out_port = None # Don't filter
    return self.table.aggregate_stats(ofp.body.match, out_port)

  
  def _stats_table (self, ofp, connection):
    #"Define estatísticas da tabela"
    # Some of these may come from the actual table(s) in the future...
    # Alguns destes podem vir da tabela real (s) no futuro ...
    r = ofp_table_stats()
    r.table_id = 0
    r.name = "Default"
    r.wildcards = OFPFW_ALL
    r.max_entries = self.max_entries
    r.active_count = len(self.table)
    r.lookup_count = self._lookup_count
    r.matched_count = self._matched_count
    return r

  
  def _stats_port (self, ofp, connection):
    #"Define estatísticas da porta"
    req = ofp.body
    if req.port_no == OFPP_NONE:
      return self.port_stats.values()
    else:
      return self.port_stats[req.port_no]

  
  def _stats_queue (self, ofp, connection):
    #"Define estatísticas da fila"
    # We don't support queues whatsoever so either send an empty list or send
    # an OFP_ERROR if an actual queue is requested.
    """ 
    Nós não suportamos filas em absoluto, então envie uma lista vazia ou envie
     # Um OFP_ERROR se uma fila real for solicitada.
    """
    req = ofp.body
    #if req.port_no != OFPP_ALL:
    #  self.send_error(type=OFPET_QUEUE_OP_FAILED, code=OFPQOFC_BAD_PORT,
    #                  ofp=ofp, connection=connection)
    # Note: We don't care about this case for now, even if port_no is bogus.
    if req.queue_id == OFPQ_ALL:
      return []
    else:
      #OFPET_QUEUE_OP_FAILED: Falha na operação da fila
      #OFPQOFC_BAD_QUEUE: A fila não existe
      self.send_error(type=OFPET_QUEUE_OP_FAILED, code=OFPQOFC_BAD_QUEUE,
                      ofp=ofp, connection=connection)


  def __repr__ (self):
    return "%s(dpid=%s, num_ports=%d)" % (type(self).__name__,
                                          dpid_to_str(self.dpid),
                                          len(self.ports))



class SoftwareSwitch (SoftwareSwitchBase, EventMixin):
  #"Classe para o software do switch"
  _eventMixin_events = set([DpPacketOut])

  
  def _output_packet_physical (self, packet, port_no):
    #"Enviar um pacote para fora uma única porta física"
    """
    send a packet out a single physical port

    This is called by the more general _output_packet().
    ---------------------------------------------------
    Isso é chamado pelo mais geral _output_packet ().
    """
    self.raiseEvent(DpPacketOut(self, packet, self.ports[port_no]))


class ExpireMixin (object):
  #"Adiciona expiração a um switch"
  """
  Adds expiration to a switch

  Inherit *before* switch base.
  -----------------------------
  Herdar * antes * alternar base.
  """
  _expire_period = 2

  def __init__ (self, *args, **kw):
    expire_period = kw.pop('expire_period', self._expire_period)
    super(ExpireMixin,self).__init__(*args, **kw)
    if not expire_period:
      # Disable
      return
    self._expire_timer = Timer(expire_period,
                               self.table.remove_expired_entries,
                               recurring=True)


class OFConnection (object):
  #"Um codec para mensagens OpenFlow."
  """
  A codec for OpenFlow messages.

  Decodes and encodes OpenFlow messages (ofp_message) into byte arrays.

  Wraps an io_worker that does the actual io work, and calls a
  receiver_callback function when a new message as arrived.
  """

  # Unlike of_01.Connection, this is persistent (at least until we implement
  # a proper recoco Connection Listener loop)
  # Globally unique identifier for the Connection instance
  """
  Decodifica e codifica mensagens OpenFlow (ofp_message) em matrizes de bytes.

   Envolve um io_worker que faz o trabalho real e chama um
   Receiver_callback função quando uma nova mensagem como chegou.
   -benzóico.

   # Ao contrário de_01.Connection, isso é persistente (pelo menos até que implementamos
   # Um loop de escuta de conexão recoco apropriado)
   # Identificador único global para a instância de conexão
  """
  ID = 0

  # See _error_handler for information the meanings of these
  # Consulte _error_handler para obter informações sobre o significado
  ERR_BAD_VERSION = 1
  ERR_NO_UNPACKER = 2
  ERR_BAD_LENGTH  = 3
  ERR_EXCEPTION   = 4

  # These methods are called externally by IOWorker
  # Esses métodos são chamados externamente pelo IOWorker

  
  def msg (self, m):
    #"Para mensagem"
    self.log.debug("%s %s", str(self), str(m))

  
  def err (self, m):
    #"Para erro"
    self.log.error("%s %s", str(self), str(m))
  
  
  def info (self, m):
    #"Para informação"
    self.log.info("%s %s", str(self), str(m))

  def __init__ (self, io_worker):
    self.starting = True # No data yet
    self.io_worker = io_worker
    self.io_worker.rx_handler = self.read
    self.controller_id = io_worker.socket.getpeername()
    OFConnection.ID += 1
    self.ID = OFConnection.ID
    self.log = logging.getLogger("ControllerConnection(id=%d)" % (self.ID,))
    self.unpackers = make_type_to_unpacker_table()

    self.on_message_received = None

  
  def set_message_handler (self, handler):
    #"Estabelece o lançamento da mensagem"
    self.on_message_received = handler

  
  def send (self, data):
    #"Enviar dados brutos para o controlador."
    """
    Send raw data to the controller.

    Generally, data is a bytes object. If not, we check if it has a pack()
    method and call it (hoping the result will be a bytes object).  This
    way, you can just pass one of the OpenFlow objects from the OpenFlow
    library to it and get the expected result, for example.
    -------------------------------------------------------------------
    Geralmente, os dados são um objeto bytes. Se não, verificamos se ele tem um pacote ()
     Método e chamá-lo (esperando o resultado será um objeto bytes). desta
     Maneira, você pode apenas passar um dos objetos OpenFlow a partir do OpenFlow
     Biblioteca para ele e obter o resultado esperado, por exemplo.
    """
    if type(data) is not bytes:
      if hasattr(data, 'pack'):
        data = data.pack()
    self.io_worker.send(data)

  
  def read (self, io_worker):
    #"Faz a leitura"
    #FIXME: Do we need to pass io_worker here?
    #Precisamos passar io_worker aqui?
    while True:
      message = io_worker.peek()
      if len(message) < 4:
        break

      # Parse head of OpenFlow message by hand
      # Analisar a mensagem do OpenFlow manualmente
      ofp_version = ord(message[0])
      ofp_type = ord(message[1])

      if ofp_version != OFP_VERSION:
        info = ofp_version
        r = self._error_handler(self.ERR_BAD_VERSION, info)
        if r is False: break
        continue

      message_length = ord(message[2]) << 8 | ord(message[3])
      if message_length > len(message):
        break

      if ofp_type >= 0 and ofp_type < len(self.unpackers):
        unpacker = self.unpackers[ofp_type]
      else:
        unpacker = None
      if unpacker is None:
        info = (ofp_type, message_length)
        r = self._error_handler(self.ERR_NO_UNPACKER, info)
        if r is False: break
        io_worker.consume_receive_buf(message_length)
        continue

      new_offset, msg_obj = self.unpackers[ofp_type](message, 0)
      if new_offset != message_length:
        info = (msg_obj, message_length, new_offset)
        r = self._error_handler(self.ERR_BAD_LENGTH, info)
        if r is False: break
        # Assume sender was right and we should skip what it told us to.
        # Suponha que o remetente estava certo e devemos ignorar o que ele nos disse.
        io_worker.consume_receive_buf(message_length)
        continue

      io_worker.consume_receive_buf(message_length)
      self.starting = False

      if self.on_message_received is None:
        raise RuntimeError("on_message_receieved hasn't been set yet!")

      try:
        self.on_message_received(self, msg_obj)
      except Exception as e:
        info = (e, message[:message_length], msg_obj)
        r = self._error_handler(self.ERR_EXCEPTION, info)
        if r is False: break
        continue

    return True

  
  def _error_handler (self, reason, info):
      #"Chamado quando read () tem um erro"
      """
      Called when read() has an error

      reason is one of OFConnection.ERR_X

      info depends on reason:
      ERR_BAD_VERSION: claimed version number
      ERR_NO_UNPACKER: (claimed message type, claimed length)
      ERR_BAD_LENGTH: (unpacked message, claimed length, unpacked length)
      ERR_EXCEPTION: (exception, raw message, unpacked message)

      Return False to halt processing of subsequent data (makes sense to
      do this if you called connection.close() here, for example).
      --------------------------------------------------------------------
       Razão é uma de OFConnection.ERR_X

       Info depende da razão:
       ERR_BAD_VERSION: número da versão reivindicada
       ERR_NO_UNPACKER: (tipo de mensagem reivindicado, comprimento reivindicado)
       ERR_BAD_LENGTH: (mensagem não embalada, comprimento reivindicado, tamanho descompactado)
       ERR_EXCEPTION: (exceção, mensagem não processada, mensagem não compactada)

       Retorna Falso para interromper o processamento de dados subseqüentes (faz sentido para
       Faça isso se você chamou connection.close () aqui, por exemplo).
      """
      if reason == OFConnection.ERR_BAD_VERSION:
        ofp_version = info
        self.log.warn('Unsupported OpenFlow version 0x%02x', info)
        if self.starting:
          message = self.io_worker.peek()
          err = ofp_error(type=OFPET_HELLO_FAILED, code=OFPHFC_INCOMPATIBLE)
          #err = ofp_error(type=OFPET_BAD_REQUEST, code=OFPBRC_BAD_VERSION)
          err.xid = self._extract_message_xid(message)
          err.data = 'Version unsupported'
          self.send(err)
        self.close()
        return False
      elif reason == OFConnection.ERR_NO_UNPACKER:
        ofp_type, message_length = info
        self.log.warn('Unsupported OpenFlow message type 0x%02x', ofp_type)
        message = self.io_worker.peek()
        err = ofp_error(type=OFPET_BAD_REQUEST, code=OFPBRC_BAD_TYPE)
        err.xid = self._extract_message_xid(message)
        err.data = message[:message_length]
        self.send(err)
      elif reason == OFConnection.ERR_BAD_LENGTH:
        msg_obj, message_length, new_offset = info
        t = type(msg_obj).__name__
        self.log.error('Different idea of message length for %s '
                       '(us:%s them:%s)' % (t, new_offset, message_length))
        message = self.io_worker.peek()
        err = ofp_error(type=OFPET_BAD_REQUEST, code=OFPBRC_BAD_LEN)
        err.xid = self._extract_message_xid(message)
        err.data = message[:message_length]
        self.send(err)
      elif reason == OFConnection.ERR_EXCEPTION:
        ex, raw_message, msg_obj = info
        t = type(ex).__name__
        self.log.exception('Exception handling %s' % (t,))
      else:
        self.log.error("Unhandled error")
        self.close()
        return False

  
  def _extract_message_xid (self, message):
    #"Extrair e retornar o xid (e comprimento) de uma mensagem openflow."
    """
    Extract and return the xid (and length) of an openflow message.
    """
    xid = 0
    if len(message) >= 8:
      #xid = struct.unpack_from('!L', message, 4)[0]
      message_length, xid = struct.unpack_from('!HL', message, 2)
    elif len(message) >= 4:
      message_length = ord(message[2]) << 8 | ord(message[3])
    else:
      message_length = len(message)
    return xid

  
  def close (self):
    #"Fechar"
    self.io_worker.shutdown()

  
  def get_controller_id (self):
    #"Retornar uma tupla do controlador (endereço, porta) estamos conectados a"
    """
    Return a tuple of the controller's (address, port) we are connected to
    """
    return self.controller_id

  def __str__ (self):
    return "[Con " + str(self.ID) + "]"


class SwitchFeatures (object):
  #"Armazena recursos do switch"
  """
  Stores switch features

  Keeps settings for switch capabilities and supported actions.
  Automatically has attributes of the form ".act_foo" for all OFPAT_FOO,
  and ".cap_foo" for all OFPC_FOO (as gathered from libopenflow).
  ----------------------------------------------------------------------
  Mantém configurações para recursos de alternância e ações suportadas.
   Automaticamente tem atributos do formulário ".act_foo" para todos OFPAT_FOO,
   E ".cap_foo" para todos OFPC_FOO (como recolhidos de libopenflow).
  """
  def __init__ (self, **kw):
    self._cap_info = {}
    for val,name in ofp_capabilities_map.iteritems():
      name = name[5:].lower() # strip OFPC_
      name = "cap_" + name
      setattr(self, name, False)
      self._cap_info[name] = val

    self._act_info = {}
    for val,name in ofp_action_type_map.iteritems():
      name = name[6:].lower() # strip OFPAT_
      name = "act_" + name
      setattr(self, name, False)
      self._act_info[name] = val

    self._locked = True

    initHelper(self, kw)

  def __setattr__ (self, attr, value):
    if getattr(self, '_locked', False):
      if not hasattr(self, attr):
        raise AttributeError("No such attribute as '%s'" % (attr,))
    return super(SwitchFeatures,self).__setattr__(attr, value)
  
  
  @property
  def capability_bits (self):
    #"Define bits de capacidade"
    #"Valor usado na resposta de recursos"
    """
    Value used in features reply
    """
    return sum( (v if getattr(self, k) else 0)
                for k,v in self._cap_info.iteritems() )
  
  
  @property
  def action_bits (self):
    #"Value used in features reply"
    #"Define as ações de bits"
    """
    Value used in features reply
    """
    return sum( (1<<v if getattr(self, k) else 0)
                for k,v in self._act_info.iteritems() )

  def __str__ (self):
    l = list(k for k in self._cap_info if getattr(self, k))
    l += list(k for k in self._act_info if getattr(self, k))
    return ",".join(l)
