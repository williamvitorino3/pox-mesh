# Copyright 2011,2012 James McCauley
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
This is a messenger service for interacting with OpenFlow.

There are lots of things that aren't implemented.  Please add!

There's now a simple webservice based on this.  If you add
functionality here, you might want to see about adding it to
the webservice too.
"""

"""
Este é um serviço de mensagens para interagir com OpenFlow .

Há muitas coisas que não são implementadas . Por favor adicione!

Há agora um webservice simples com base nesta . Se você adicionar
funcionalidade aqui, você pode querer ver sobre adicionando-a a
o webservice também.
"""
from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.messenger import *
"sys: Um dicionário agindo como um cache para localizador de objectos."
import sys

"""
traceback: Este módulo fornece uma interface padrão para extrair, 
de formato e de pilha de impressão vestígios de programas em Python. 
É exatamente imita o comportamento do interpretador Python 
quando se imprime um rastreamento de pilha. Isso é útil 
quando você quiser imprimir rastreamentos de pilha sob controle do programa, 
tal como em um "wrapper" em torno do intérprete.
"""
import traceback
from pox.openflow.of_json import *
from pox.lib.util import dpidToStr,strToDPID


log = core.getLogger()

def _type_str (m):
  return of.ofp_type_map.get(m.header_type, str(m.header_type))


def _ofp_entry (event):
  ofp = event.ofp
  """
  isinstance: Retorna verdadeiro se o objeto argumento é uma instância da ClassInfo argumento, ou de um (direta, indireta ou virtual subclasse) da mesma.
  Se objeto não é uma instância de classe ou um objeto do tipo de dado, a função sempre retorna false.
  """
  if isinstance(ofp, list):
    ofp = ofp[0];
  m = { 'xid' : ofp.xid,
        'dpid' : dpidToStr(event.connection.dpid), "um DPID cadeia flui - uma lista de entradas de fluxo"
        'type_str' : _type_str(ofp),
        'header_type' : ofp.header_type,
      }
  return m


"Classe para inicialização do canal"
class OFBot (ChannelBot):
  def _init (self, extra):
    self.enable_packet_ins = False
    self.oflisteners = core.openflow.addListeners(self)

  "Destruir"
  def _destroyed (self):
    core.openflow.removeListeners(self.oflisteners)

  "Lida com conexão 'alta'"
  def _handle_ConnectionUp (self, event):
    #self.send(_ofp_entry(event))
    m = { 'type_str' : 'ConnectionUp', 'dpid' : dpidToStr(event.dpid) }
    self.send(m)

  "Lida com conexão 'baixa'"
  def _handle_ConnectionDown (self, event):
    m = { 'type_str' : 'ConnectionDown', 'dpid' : dpidToStr(event.dpid) }
    self.send(m)

  "Lida com a 'barreira'"
  def _handle_BarrierIn (self, event):
    self.send(_ofp_entry(event))

  "Lida com erro"
  def _handle_ErrorIn (self, event):
    m = { 'type' : event.ofp.type, 'code' : event.ofp.code,
          'msg' : event.asString(),
        }
    m.update(_ofp_entry(event))
    self.send(m)

  "Lida com o switch recebido. Obtém mudar detalhes . DPID - um DPID string"
  def _handle_SwitchDescReceived (self, event):
    m = _ofp_entry(event)
    m['switch_desc'] = switch_desc_to_dict(event.stats)
    self.send(m)

  "Lida com o estado do fluxo recebido"
  def _handle_FlowStatsReceived (self, event):
    m = _ofp_entry(event)
    m['flow_stats'] = flow_stats_to_list(event.stats)
    self.send(m)
 
  "Lida com o pacote"
  def _handle_PacketIn (self, event):
    if not self.enable_packet_ins: return
    if len(self.channel._members) == 0: return
    m = { 'buffer_id' : event.ofp.buffer_id, "ID atribuída pelo datapath"
          'total_len' : event.ofp._total_len, "tamanho do pacote"
          'in_port' : event.ofp.in_port, "porta de entrada do pacote"
          'reason' : event.ofp.reason,  "razão"
          #'data' : event.data,
        }
    m['payload'] = fix_parsed(event.parsed)
    m.update(_ofp_entry(event))

#    import json
#    try:
#      json.dumps(m,indent=2)
#    except:
#      print json.dumps(m,encoding="latin1",indent=2)

    self.send(m)

  "executa o pacote para fora"
  def _exec_cmd_packet_out (self, event):
    try:
      msg = event.msg
      dpid = strToDPID(msg['dpid'])
      con = core.openflow.getConnection(dpid)
      if con is None:
        raise RuntimeError("No such switch")
      po = dict_to_packet_out(msg)
      con.send(po)

    except:
      log.exception("Exception in packet_out")
      self.reply(event,
                 exception="%s: %s" % (sys.exc_info()[0],sys.exc_info()[1]),
                 traceback=traceback.format_exc())

  "executa o estado do fluxo. Obter lista de fluxos sobre a mesa . DPID - um DPID cadeia. match - estrutura de match ( opcional, padrão para coincidir com todos)"
  def _exec_cmd_get_flow_stats (self, event):
    try:
      msg = event.msg
      dpid = strToDPID(msg['dpid'])
      con = core.openflow.getConnection(dpid)
      if con is None:
        raise RuntimeError("No such switch") "No such switch: sem essa mudança"

      match = event.msg.get('match') "Descrição dos campos"
      table_id = event.msg.get('table_id', 0xff) "table_id: mesa para fluxos ( padrão para todos).indica o próximo mesa no pipeline de processamento de pacotes."
      """
      Para comandos OFPFC_DELETE * , requerem
      entradas correspondentes para incluir isso como uma
      porta de saída . Um valor de OFPP_ANY
      indica nenhuma restrição
      """
      "out_port: filtro por porta de saída (padrão para todos)"
      out_port = event.msg.get('out_port', of.OFPP_NONE) 

      sr = of.ofp_stats_request()
      sr.body = of.ofp_flow_stats_request()
      if match is None:
        match = of.ofp_match()
      else:
        match = dict_to_match(match)
      sr.body.match = match
      sr.body.table_id = table_id
      sr.body.out_port = out_port
      con.send(sr)
      self.reply(event,**{'type':'set_table','xid':sr.xid})

    except:
      #log.exception("Exception in get_flow_stats")
      log.debug("Exception in get_flow_stats - %s:%s",
                sys.exc_info()[0].__name__,
                sys.exc_info()[1])
      self.reply(event,
                 exception="%s: %s" % (sys.exc_info()[0],sys.exc_info()[1]),
                 traceback=traceback.format_exc())

  "executa o conjunto da mesa. Define a tabela de fluxo em um switch"
  def _exec_cmd_set_table (self, event):
    try:
      msg = event.msg
      dpid = strToDPID(msg['dpid'])
      con = core.openflow.getConnection(dpid)
      if con is None:
        raise RuntimeError("No such switch")

      xid = of.generate_xid()

      """
      As modificações em um tabela de fluxo do controlador é feito com a mensagem OFPT_FLOW_MOD
      """
      fm = of.ofp_flow_mod()
      fm.xid = xid
      "OFPFC_DELETE: Exclui todos os fluxos correspondentes .."
      fm.command = of.OFPFC_DELETE
      con.send(fm)
      bar = of.ofp_barrier_request()
      bar.xid = xid
      con.send(bar)

      for flow in msg.get('flows',[]):
        fm = dict_to_flow_mod(flow)
        fm.xid = xid

        con.send(fm)
        #con.send(of.ofp_barrier_request(xid=xid))
      con.send(of.ofp_barrier_request(xid=xid))

      self.reply(event,**{'type':'set_table','xid':xid})

    except:
      #log.exception("Exception in set_table")
      log.debug("Exception in set_table - %s:%s",
                sys.exc_info()[0].__name__,
                sys.exc_info()[1])
      self.reply(event,
                 exception="%s: %s" % (sys.exc_info()[0],sys.exc_info()[1]),
                 traceback=traceback.format_exc())

  #TODO: You should actually be able to configure packet in messages...
  #      for example, enabling raw data of the whole packet, and
  #      raw of individual parts.

  """
  Você deve realmente ser capaz de configurar pacotes em mensagens ...
  # Por exemplo , permitindo que os dados brutos de todo o pacote , e
  # Crua de partes individuais.
  """
  def _exec_packetins_True (self, event):
    self.enable_packet_ins = True

  def _exec_packetins_False (self, event):
    self.enable_packet_ins = False

  "excuta a lista de swtiches. Obter lista de opções e suas informações básicas "
  def _exec_cmd_list_switches (self, event):
    r = list_switches()
    self.send(switch_list = r)


def launch (nexus = "MessengerNexus"):
  def _launch ():
    # Make invitable
    core.MessengerNexus.default_bot.add_bot(OFBot)

    # Just stick one in a channel
    "Basta ficar um em um canal"
    OFBot("of_01")

    # For now, just register something arbitrary so that we can use
    # this for dependencies
    """
    por agora, apenas registrar algo arbitrário para que possamos usar
    Isso para dependências
    """
    core.register(nexus + "_of_service", object())

  core.call_when_ready(_launch, [nexus, "openflow"])
