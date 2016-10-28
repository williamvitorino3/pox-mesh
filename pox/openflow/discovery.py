# Copyright 2011-2013 James McCauley
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

# This file is loosely based on the discovery component in NOX.

"""
openflow.discovery: Utiliza mensagens LLDP (Link Layer Discovery Protocol) 
para descobrir a conectividade entre os switches com o objetivo de mapear 
a topologia da rede. O mesmo cria eventos (os quais podem ser “escutados”) 
quando um link fica up ou down. Esse componente foi essencial para a aplicação desenvolvida;

Este módulo descobre a conectividade entre switches OpenFlow enviando
fora pacotes LLDP . Para ser notificado desta informação , ouvir LinkEvents
em core.openflow_discovery .

É possível que alguns dos isso deve ser abstraída para fora em um genérico
módulo de descoberta , ou uma superclasse Discovery.

This module discovers the connectivity between OpenFlow switches by sending
out LLDP packets. To be notified of this information, listen to LinkEvents
on core.openflow_discovery.

It's possible that some of this should be abstracted out into a generic
Discovery module, or a Discovery superclass.
"""

from pox.lib.revent import *
from pox.lib.recoco import Timer
from pox.lib.util import dpid_to_str, str_to_bool
from pox.core import core
import pox.openflow.libopenflow_01 as of
import pox.lib.packet as pkt

import struct
import time
from collections import namedtuple
from random import shuffle, random


log = core.getLogger()

"Envia pacotes descobertos"
class LLDPSender (object):

  SendItem = namedtuple("LLDPSenderItem", ('dpid','port_num','packet'))

  """
  sua classe mantém os pacotes para enviar em uma lista simples , o que torna
  Adicionar / remover -los na chave juntar / licença ou (especialmente) porta
  Mudanças de status relativamente caro . Poderia ser facilmente melhorado.
  """
  #NOTE: This class keeps the packets to send in a flat list, which makes
  #      adding/removing them on switch join/leave or (especially) port
  #      status changes relatively expensive. Could easily be improved.

  # Maximum times to run the timer per second
  "tempo máximo para executar o temporizador por segundo"
  _sends_per_sec = 15

"""
Inicializar um pacote remetente LLDP

send_cycle_time é o tempo ( em segundos) que este remetente vai demorar para
enviar todos os pacotes de descoberta. Assim , ele deve ser o elo de tempo limite
intervalo de , no máximo.

TTL é o tempo ( em segundos) para que um agente LLDP recepção deve
considerar o resto dos dados para ser válido. Nós não usamos isso, mas
outros agentes LLDP pode. não pode ser 0 (isto significa revogar ) .
"""
  def __init__ (self, send_cycle_time, ttl = 120):
    """
    Initialize an LLDP packet sender

    send_cycle_time is the time (in seconds) that this sender will take to
      send every discovery packet.  Thus, it should be the link timeout
      interval at most.

    ttl is the time (in seconds) for which a receiving LLDP agent should
      consider the rest of the data to be valid.  We don't use this, but
      other LLDP agents might.  Can't be 0 (this means revoke).
    """
    # Packets remaining to be sent in this cycle
    "Pacotes restantes a serem enviados neste ciclo"
    self._this_cycle = []

    # Packets we've already sent in this cycle
    "Os pacotes que já enviaram neste ciclo"
    self._next_cycle = []

    # Packets to send in a batch
    "Pacotes para enviar em um lote"
    self._send_chunk_size = 1

    self._timer = None
    self._ttl = ttl
    self._send_cycle_time = send_cycle_time
    core.listen_to_dependencies(self)

  "Acompanhar as mudanças para alternar portas"
  def _handle_openflow_PortStatus (self, event):
    if event.added:
      self.add_port(event.dpid, event.port, event.ofp.desc.hw_addr)
    elif event.deleted:
      self.del_port(event.dpid, event.port)

  def _handle_openflow_ConnectionUp (self, event):
    self.del_switch(event.dpid, set_timer = False)

    ports = [(p.port_no, p.hw_addr) for p in event.ofp.ports]

    for port_num, port_addr in ports:
      self.add_port(event.dpid, port_num, port_addr, set_timer = False)

    self._set_timer()

  def _handle_openflow_ConnectionDown (self, event):
    self.del_switch(event.dpid)

  "deleta switch"
  def del_switch (self, dpid, set_timer = True):
    self._this_cycle = [p for p in self._this_cycle if p.dpid != dpid]
    self._next_cycle = [p for p in self._next_cycle if p.dpid != dpid]
    if set_timer: self._set_timer()

  "deleta porta"
  def del_port (self, dpid, port_num, set_timer = True):
    if port_num > of.OFPP_MAX: return
    self._this_cycle = [p for p in self._this_cycle
                        if p.dpid != dpid or p.port_num != port_num]
    self._next_cycle = [p for p in self._next_cycle
                        if p.dpid != dpid or p.port_num != port_num]
    if set_timer: self._set_timer()

  "adiciona porta"
  def add_port (self, dpid, port_num, port_addr, set_timer = True):
    if port_num > of.OFPP_MAX: return
    self.del_port(dpid, port_num, set_timer = False)
    self._next_cycle.append(LLDPSender.SendItem(dpid, port_num,
          self.create_discovery_packet(dpid, port_num, port_addr)))
    if set_timer: self._set_timer()

  "estabelece o temporizador"
  def _set_timer (self):
    if self._timer: self._timer.cancel()
    self._timer = None
    num_packets = len(self._this_cycle) + len(self._next_cycle)

    if num_packets == 0: return

    self._send_chunk_size = 1 # One at a time
    interval = self._send_cycle_time / float(num_packets)
    "Exigiria muitos envia por segundo - enviar mais de um ao mesmo tempo"
    if interval < 1.0 / self._sends_per_sec:
      # Would require too many sends per sec -- send more than one at once
      interval = 1.0 / self._sends_per_sec
      chunk = float(num_packets) / self._send_cycle_time / self._sends_per_sec
      self._send_chunk_size = chunk

    self._timer = Timer(interval,
                        self._timer_handler, recurring=True)

  """
  Chamado por um temporizador para realmente enviar pacotes .
  Pega o primeiro pacote de fora da lista deste ciclo, envia -lo, 
  e em seguida, coloca-lo na lista de próxima ciclo. 
  Quando a lista deste ciclo é vazio, começa o ciclo seguinte .
  """
  def _timer_handler (self):
    """
    Called by a timer to actually send packets.

    Picks the first packet off this cycle's list, sends it, and then puts
    it on the next-cycle list.  When this cycle's list is empty, starts
    the next cycle.
    """
    num = int(self._send_chunk_size)
    fpart = self._send_chunk_size - num
    if random() < fpart: num += 1

    for _ in range(num):
      if len(self._this_cycle) == 0:
        self._this_cycle = self._next_cycle
        self._next_cycle = []
        #shuffle(self._this_cycle)
      item = self._this_cycle.pop(0)
      self._next_cycle.append(item)
      core.openflow.sendToDPID(item.dpid, item.packet)

  "Constroir pacote descoberto"
  def create_discovery_packet (self, dpid, port_num, port_addr):
    """
    Build discovery packet
    """

    chassis_id = pkt.chassis_id(subtype=pkt.chassis_id.SUB_LOCAL)
    chassis_id.id = bytes('dpid:' + hex(long(dpid))[2:-1])
    # Maybe this should be a MAC.  But a MAC of what?  Local port, maybe?

    port_id = pkt.port_id(subtype=pkt.port_id.SUB_PORT, id=str(port_num))

    ttl = pkt.ttl(ttl = self._ttl)

    sysdesc = pkt.system_description()
    sysdesc.payload = bytes('dpid:' + hex(long(dpid))[2:-1])

    discovery_packet = pkt.lldp()
    discovery_packet.tlvs.append(chassis_id)
    discovery_packet.tlvs.append(port_id)
    discovery_packet.tlvs.append(ttl)
    discovery_packet.tlvs.append(sysdesc)
    discovery_packet.tlvs.append(pkt.end_tlv())

    eth = pkt.ethernet(type=pkt.ethernet.LLDP_TYPE)
    eth.src = port_addr
    eth.dst = pkt.ETHERNET.NDP_MULTICAST
    eth.payload = discovery_packet

    po = of.ofp_packet_out(action = of.ofp_action_output(port=port_num))
    po.data = eth.pack()
    return po.pack()

"Vincular up / down evento"
class LinkEvent (Event):
  """
  Link up/down event
  """
  def __init__ (self, add, link):
    Event.__init__(self)
    self.link = link
    self.added = add
    self.removed = not add

  def port_for_dpid (self, dpid):
    if self.link.dpid1 == dpid:
      return self.link.port1
    if self.link.dpid2 == dpid:
      return self.link.port2
    return None

"""
  Retorna uma versão " unidirecional " desta ligação

  As versões unidireccionais de chaves simétricas será igual
  """
class Link (namedtuple("LinkBase",("dpid1","port1","dpid2","port2"))):
  @property
  def uni (self):
    """
    Returns a "unidirectional" version of this link

    The unidirectional versions of symmetric keys will be equal
    """
    pairs = list(self.end)
    pairs.sort()
    return Link(pairs[0][0],pairs[0][1],pairs[1][0],pairs[1][1])

  @property
  def end (self):
    return ((self[0],self[1]),(self[2],self[3]))

  def __str__ (self):
    return "%s.%s -> %s.%s" % (dpid_to_str(self[0]),self[1],
                               dpid_to_str(self[2]),self[3])

  def __repr__ (self):
    return "Link(dpid1=%s,port1=%s, dpid2=%s,port2=%s)" % (self.dpid1,
        self.port1, self.dpid2, self.port2)

"""
Componente que tenta descobrir da topologia de rede.

Envia pacotes LLDP especialmente criados , e monitora a sua chegada .
"""
class Discovery (EventMixin):
  """
  Component that attempts to discover network toplogy.

  Sends out specially-crafted LLDP packets, and monitors their arrival.
  """

  "Prioridade do fluxo de captura LLDP (se houver)"
  _flow_priority = 65000     # Priority of LLDP-catching flow (if any) 
  "Quanto tempo até que nós consideramos um beco sem ligação"
  _link_timeout = 10         # How long until we consider a link dead
  "Quantas vezes para verificar se há tempos de espera"
  _timeout_check_period = 5  # How often to check for timeouts

  _eventMixin_events = set([
    LinkEvent,
  ])

  _core_name = "openflow_discovery" # we want to be core.openflow_discovery

  Link = Link

  def __init__ (self, install_flow = True, explicit_drop = True,
                link_timeout = None, eat_early_packets = False):
    self._eat_early_packets = eat_early_packets
    self._explicit_drop = explicit_drop
    self._install_flow = install_flow
    if link_timeout: self._link_timeout = link_timeout

    self.adjacency = {} # From Link to time.time() stamp
    self._sender = LLDPSender(self.send_cycle_time)

    # Listen with a high priority (mostly so we get PacketIns early)
    "Ouça com uma alta prioridade (principalmente então temos PacketIns início )"
    core.listen_to_dependencies(self,
        listen_args={'openflow':{'priority':0xffffffff}})

    Timer(self._timeout_check_period, self._expire_links, recurring=True)

  @property
  def send_cycle_time (self):
    return self._link_timeout / 2.0

  "instala o fluxo"
  def install_flow (self, con_or_dpid, priority = None):
    if priority is None:
      priority = self._flow_priority
    if isinstance(con_or_dpid, (int,long)):
      con = core.openflow.connections.get(con_or_dpid)
      if con is None:
        log.warn("Can't install flow for %s", dpid_to_str(con_or_dpid))
        return False
    else:
      con = con_or_dpid

    match = of.ofp_match(dl_type = pkt.ethernet.LLDP_TYPE,
                          dl_dst = pkt.ETHERNET.NDP_MULTICAST)
    msg = of.ofp_flow_mod()
    msg.priority = priority
    msg.match = match
    msg.actions.append(of.ofp_action_output(port = of.OFPP_CONTROLLER)) "OFPP_CONTROLLER: Enviar para o controlador"
    con.send(msg)
    return True

  def _handle_openflow_ConnectionUp (self, event):
    if self._install_flow:
      # Make sure we get appropriate traffic
      "Certifique-se de que obter o tráfego adequado"
      log.debug("Installing flow for %s", dpid_to_str(event.dpid))
      self.install_flow(event.connection)

  "Excluir todos os links nesta interruptor"
  def _handle_openflow_ConnectionDown (self, event):
    # Delete all links on this switch
    self._delete_links([link for link in self.adjacency
                        if link.dpid1 == event.dpid
                        or link.dpid2 == event.dpid])

  "remover links aparentemente mortos"
  def _expire_links (self):
    """
    Remove apparently dead links
    """
    now = time.time()

    expired = [link for link,timestamp in self.adjacency.iteritems()
               if timestamp + self._link_timeout < now]
    if expired:
      for link in expired:
        log.info('link timeout: %s', link)

      self._delete_links(expired)

  "Receber e processar pacotes LLDP"
  def _handle_openflow_PacketIn (self, event):
    """
    Receive and process LLDP packets
    """

    packet = event.parsed

    if (packet.effective_ethertype != pkt.ethernet.LLDP_TYPE
        or packet.dst != pkt.ETHERNET.NDP_MULTICAST):
      if not self._eat_early_packets: return
      if not event.connection.connect_time: return
      enable_time = time.time() - self.send_cycle_time - 1
      if event.connection.connect_time > enable_time:
        return EventHalt
      return

    if self._explicit_drop:
      if event.ofp.buffer_id is not None:
        log.debug("Dropping LLDP packet %i", event.ofp.buffer_id)
        msg = of.ofp_packet_out()
        msg.buffer_id = event.ofp.buffer_id
        msg.in_port = event.port
        event.connection.send(msg)

    lldph = packet.find(pkt.lldp)
    if lldph is None or not lldph.parsed:
      log.error("LLDP packet could not be parsed") #LLDP pacote não pôde ser analisada"
      return EventHalt
    if len(lldph.tlvs) < 3:
      log.error("LLDP packet without required three TLVs") #pacote LLDP sem necessárias três TLVs"
      return EventHalt
    if lldph.tlvs[0].tlv_type != pkt.lldp.CHASSIS_ID_TLV:
      log.error("LLDP packet TLV 1 not CHASSIS_ID")
      return EventHalt
    if lldph.tlvs[1].tlv_type != pkt.lldp.PORT_ID_TLV:
      log.error("LLDP packet TLV 2 not PORT_ID")
      return EventHalt
    if lldph.tlvs[2].tlv_type != pkt.lldp.TTL_TLV:
      log.error("LLDP packet TLV 3 not TTL")
      return EventHalt

    def lookInSysDesc ():
      r = None
      for t in lldph.tlvs[3:]:
        if t.tlv_type == pkt.lldp.SYSTEM_DESC_TLV:
          # This is our favored way...
          for line in t.payload.split('\n'):
            if line.startswith('dpid:'):
              try:
                return int(line[5:], 16)
              except:
                pass
          if len(t.payload) == 8:
            # Maybe it's a FlowVisor LLDP...
            # Do these still exist?
            try:
              return struct.unpack("!Q", t.payload)[0]
            except:
              pass
          return None

    originatorDPID = lookInSysDesc()

    if originatorDPID == None:
      # We'll look in the CHASSIS ID
      if lldph.tlvs[0].subtype == pkt.chassis_id.SUB_LOCAL:
        if lldph.tlvs[0].id.startswith('dpid:'):
          # This is how NOX does it at the time of writing
          "Isto é como NOX faz isso no momento da escrita"
          try:
            originatorDPID = int(lldph.tlvs[0].id[5:], 16)
          except:
            pass
      if originatorDPID == None:
        if lldph.tlvs[0].subtype == pkt.chassis_id.SUB_MAC:
          # Last ditch effort -- we'll hope the DPID was small enough
          # to fit into an ethernet address
          """
          Último esforço - vamos esperar que o DPID era pequeno o suficiente
          # Para caber em um endereço ethernet
          """
          if len(lldph.tlvs[0].id) == 6:
            try:
              s = lldph.tlvs[0].id
              originatorDPID = struct.unpack("!Q",'\x00\x00' + s)[0]
            except:
              pass

    if originatorDPID == None:
      log.warning("Couldn't find a DPID in the LLDP packet") "Não foi possível encontrar um DPID no pacote LLDP"
      return EventHalt

    if originatorDPID not in core.openflow.connections:
      log.info('Received LLDP packet from unknown switch') "Pacote recebido LLDP do interruptor desconhecido"
      return EventHalt

    # Get port number from port TLV
    "Obter número da porta de TLV porta"
    if lldph.tlvs[1].subtype != pkt.port_id.SUB_PORT:
      log.warning("Thought we found a DPID, but packet didn't have a port") #Pensado que encontramos um DPID , mas pacotes não têm uma porta"
      return EventHalt
    originatorPort = None
    if lldph.tlvs[1].id.isdigit():
      # We expect it to be a decimal value
      "Esperamos que ele seja um valor decimal"
      originatorPort = int(lldph.tlvs[1].id)
    elif len(lldph.tlvs[1].id) == 2:
      # Maybe it's a 16 bit port number...
      "Talvez seja um número de porta de 16 bits "
      try:
        originatorPort  =  struct.unpack("!H", lldph.tlvs[1].id)[0]
      except:
        pass
    if originatorPort is None:
      log.warning("Thought we found a DPID, but port number didn't " +
                  "make sense")
      return EventHalt

    if (event.dpid, event.port) == (originatorDPID, originatorPort):
      log.warning("Port received its own LLDP packet; ignoring") #Porta recebeu o seu próprio pacote LLDP ; ignorando "
      return EventHalt

    link = Discovery.Link(originatorDPID, originatorPort, event.dpid,
                          event.port)

    if link not in self.adjacency:
      self.adjacency[link] = time.time()
      log.info('link detected: %s', link)
      self.raiseEventNoErrors(LinkEvent, True, link)
    else:
      # Just update timestamp
      "Apenas atualização timestamp"
      self.adjacency[link] = time.time()

    "Provavelmente, ninguém mais precisa neste evento"
    return EventHalt # Probably nobody else needs this event

  def _delete_links (self, links):
    for link in links:
      self.raiseEventNoErrors(LinkEvent, False, link)
    for link in links:
      self.adjacency.pop(link, None)

 "Retornar true se determinada porta não se conectar a outro switch"
 def is_edge_port (self, dpid, port):
    """
    Return True if given port does not connect to another switch
    """
    for link in self.adjacency:
      if link.dpid1 == dpid and link.port1 == port:
        return False
      if link.dpid2 == dpid and link.port2 == port:
        return False
    return True

"inicializa"
def launch (no_flow = False, explicit_drop = True, link_timeout = None,
            eat_early_packets = False):
  explicit_drop = str_to_bool(explicit_drop)
  eat_early_packets = str_to_bool(eat_early_packets)
  install_flow = not str_to_bool(no_flow)
  if link_timeout: link_timeout = int(link_timeout)

  core.registerNew(Discovery, explicit_drop=explicit_drop,
                   install_flow=install_flow, link_timeout=link_timeout,
                   eat_early_packets=eat_early_packets)
