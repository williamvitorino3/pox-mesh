# -*- coding: utf-8 -*-

# Copyright 2011 James McCauley
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
This is the main OpenFlow module.

Along with libopenflow, this is the major part of the OpenFlow API in POX.
There are a number of Events, which are generally raised on core.openflow
as well as on individual switch Connections.  Many of these events have at
least some of the following properties:
 .connection - a reference to the switch connection that caused the event
 .dpid - the DPID of the switch that caused the event
 .ofp - the OpenFlow message that caused the event (from libopenflow)

One of the more complicated aspects of OpenFlow is dealing with stats
replies, which may come in multiple parts (it shouldn't be that that
difficult, really, but that hasn't stopped it from beind handled wrong
wrong more than once).  In POX, the raw events are available, but you will
generally just want to listen to the aggregate stats events which take
care of this for you and are only fired when all data is available.

NOTE: This module is usually automatically loaded by pox.py
"""

"""

Este é o módulo OpenFlow principal .

Juntamente com libopenflow , esta é a maior parte da API OpenFlow em POX .
Há uma série de eventos , que são geralmente criados em core.openflow
bem como sobre Conexões de switch individuais. Muitos destes acontecimentos têm pelo
pelo menos alguns dos seguintes propriedades :
 .connection - uma referência para a conexão do comutador que causou o evento
 .dpid - o DPID do interruptor que causou o evento
 .ofp - a mensagem OpenFlow que causou o evento ( da libopenflow )

Um dos aspectos mais complicados de OpenFlow é lidar com estatísticas
respostas, que podem entrar em várias partes ( não deve ser aquela que
difícil, realmente, mas que não impediu de beind tratadas errado
errado mais de uma vez ) . Em POX , os eventos brutos estão disponíveis , mas você vai
geralmente só quer ouvir o agregado Status de eventos que levam
cuidado deste para você e somente são acionados quando todos os dados está disponível .

NOTA: Este módulo é normalmente carregado automaticamente pelo pox.py
"""

from pox.lib.revent import *
from pox.lib.util import dpidToStr
import libopenflow_01 as of
from pox.lib.packet.ethernet import ethernet

"Evento disparado quando a conexão com um switch OpenFlow tem sido estabelecida ."
class ConnectionUp (Event):

  "Chamado após a instância foi criada (por __new__()), "
  "mas antes de ser retornado para o chamador. "
  "Os argumentos são aqueles passados ​​para a expressão construtor da classe. "
  "Se uma classe base tem um __init__()método, o da classe derivada __init__()método, "
  "se houver, deve chamá-lo explicitamente para garantir a inicialização adequada "
  "da parte da classe base da instância; por exemplo: .BaseClass.__init__(self, [args...])"

  def __init__ (self, connection, ofp):
    Event.__init__(self)
    self.connection = connection
    self.dpid = connection.dpid
    self.ofp = ofp

class FeaturesReceived (Event):
  """
    Levantadas após o recebimento de uma mensagem de ofp_switch_features
    Isso geralmente acontece como parte de uma conexão automaticamente .
  """
  def __init__ (self, connection, ofp):
    Event.__init__(self)
    self.connection = connection
    self.dpid = connection.dpid
    self.ofp = ofp

"Evento disparado quando a conexão com um switch OpenFlow tem sido perdido."
class ConnectionDown (Event):

  def __init__ (self, connection):
    Event.__init__(self)
    self.connection = connection
    self.dpid = connection.dpid

"""
Demitido em resposta às mudanças de estado das portas .
  acrescentado ( bool) - Verdadeiro se demitido porque uma porta foi adicionada
  suprimido (bool ) - True se demitido porque uma porta foi excluída
  modificada (bool ) - True se demitido porque uma porta foi modificado
  port (int) - número de porto em questão

PortStatus: 
Informar o controlador de uma mudança em uma porta . O interruptor é esperado para enviar porta -status
mensagens para os controladores como configuração da porta ou alterações Estado do porto. Estes eventos incluem mudança de
eventos de configuração de porta , por exemplo, se ele foi trazido para baixo diretamente por um usuário , e mudança de estado da porta
eventos , por exemplo, se a ligação caiu.
"""
class PortStatus (Event):

  def __init__ (self, connection, ofp):
    Event.__init__(self)
    self.connection = connection
    self.dpid = connection.dpid #"o DPID do interruptor que causou o evento"
    self.ofp = ofp #"a mensagem OpenFlow que causou o evento ( da libopenflow )"
    self.modified = ofp.reason == of.OFPPR_MODIFY #"Algum atributo da porta mudou"
    self.added = ofp.reason == of.OFPPR_ADD #"A porta foi adicionada"
    self.deleted = ofp.reason == of.OFPPR_DELETE #"A porta foi removida"
    self.port = ofp.desc.port_no

"""
Ocorre quando uma entrada de fluxo foi removido a partir de uma mesa de fluxo .
  Isto pode ser quer devido a um tempo de espera ou porque foi removido
  explicitamente.
  propriedades:
  idleTimeout (bool ) - True se expirou por causa da ociosidade
  hardTimeout (bool ) - True se expirou por causa do tempo limite de disco
  timeout ( bool ) - True se qualquer um dos acima é verdadeiro
  suprimido (bool ) - True se excluídos explicitamente

Fluxo - Removido : informar o controlador sobre a remoção de uma entrada de fluxo de uma tabela de fluxo. Fluxo-
mensagens removidas são enviados apenas para as entradas de fluxo com a flag OFPFF_SEND_FLOW_REM . Eles são
gerados como resultado de um fluxo controlador excluir pedido ou o fluxo de processo de termo interruptor quando um de
o tempo limite de fluxo for excedido
"""
class FlowRemoved (Event):
  
  def __init__ (self, connection, ofp):
    Event.__init__(self)
    self.connection = connection
    self.dpid = connection.dpid
    self.ofp = ofp
    self.idleTimeout = False #"idleTimeout: idle timeout de modificação fluxo inicial."
    self.hardTimeout = False #"hardTimeout: tempo limite rígido de modificação fluxo de originais"
    self.deleted = False
    self.timeout = False
    if ofp.reason == of.OFPRR_IDLE_TIMEOUT: #"OFPRR_IDLE_TIMEOUT: Fluxo tempo ocioso excedeu idle_timeout "
      self.timeout = True
      self.idleTimeout = True
    elif ofp.reason == of.OFPRR_HARD_TIMEOUT: #"OFPRR_HARD_TIMEOUT: Tempo excedido hard_timeout"
      self.timeout = True
      self.hardTimeout = True
    elif ofp.reason == of.OFPRR_DELETE: #"OFPRR_DELETE: Despejados por um mod fluxo DELETE."
      self.deleted = True

class RawStatsReply (Event):
  def __init__ (self, connection, ofp):
    Event.__init__(self)
    self.connection = connection
    self.ofp = ofp     # Raw ofp message(s)

  @property
  def dpid (self):
    return self.connection.dpid

"superclasse abstrata para todas as estatísticas respostas"
class StatsReply (Event):
  def __init__ (self, connection, ofp, stats):
    Event.__init__(self)
    self.connection = connection
    self.ofp = ofp     # Raw ofp message(s)
    self.stats = stats # Processed

  @property
  def dpid (self):
    return self.connection.dpid

class SwitchDescReceived (StatsReply):
  pass

class FlowStatsReceived (StatsReply):
  pass

class AggregateFlowStatsReceived (StatsReply):
  pass

class TableStatsReceived (StatsReply):
  pass

class PortStatsReceived (StatsReply):
  pass

class QueueStatsReceived (StatsReply):
  pass


class PacketIn (Event):
  """
  Packet -in : transferir o controlador de um pacote para o controlador . Para todos os pacotes enviados para o controlador
  porta reservada usando uma entrada de fluxo ou a entrada de fluxo de mesa -miss , um evento pacote -in é sempre
  enviado aos controladores. Outros processamento , tais como a verificação de TTL , também pode gerar pacotes -in eventos
  para enviar pacotes para o controlador.

  Demitido em resposta a eventos PacketIn
    port (int) - número de porta que o pacote está vindo
    dados (bytes) - de pacote de dados em bruto
    analisados ​​( subclasses de pacotes ) - versão analisada do pox.lib.packet
  """
  def __init__ (self, connection, ofp):
    Event.__init__(self)
    self.connection = connection
    self.ofp = ofp
    self.port = ofp.in_port
    self.data = ofp.data
    self._parsed = None
    self.dpid = connection.dpid

  def parse (self):
    if self._parsed is None:
      self._parsed = ethernet(self.data)
    return self._parsed

  @property
  def parsed (self):
    "O pacote como analisado pelo pox.lib.packet"
    return self.parse()

class ErrorIn (Event):
  def __init__ (self, connection, ofp):
    Event.__init__(self)
    self.connection = connection
    self.ofp = ofp
    self.xid = ofp.xid
    self.dpid = connection.dpid
    self.should_log = True # If this remains True, an error will be logged

  def asString (self):
    return self.ofp.show()

#    def lookup (m, v):
#      if v in m:
#        return str(m[v])
#      else:
#        return "Unknown/" + str(v)
#
#    #TODO: The show() in ofp_error actually does some clever
#    #      stuff now to stringize error messages.  Refactor that and the
#    #      (less clever) code below.
#    s = 'Type: ' + lookup(of.ofp_error_type_map, self.ofp.type)
#    s += ' Code: '
#
#    responses = {
#      of.OFPET_HELLO_FAILED    : of.ofp_hello_failed_code, #Olá protocolo falhou
#      of.OFPET_BAD_REQUEST     : of.ofp_bad_request_code, #Pedido não foi compreendido
#      of.OFPET_BAD_ACTION      : of.ofp_bad_action_code, #Erro na descrição da ação
#      of.OFPET_FLOW_MOD_FAILED : of.ofp_flow_mod_failed_code, #Problema modificando a entrada de fluxo.
#      of.OFPET_PORT_MOD_FAILED : of.ofp_port_mod_failed_code, #Pedido da porta mod falhou
#      of.OFPET_QUEUE_OP_FAILED : of.ofp_queue_op_failed_code, #operação fila falhou.
#    }
#
#    if self.ofp.type in responses:
#      s += lookup(responses[self.ofp.type],self.ofp.code)
#    else:
#      s += "Unknown/" + str(self.ofp.code)
#    if self.ofp.type == of.OFPET_HELLO_FAILED:
#      s += lookup(of.ofp_hello_failed_code, self.ofp.type)
#
#    return s

"""
Disparados em resposta a uma resposta barreira
  XID ( int) - XID de solicitação de barreira
"""
class BarrierIn (Event):

  def __init__ (self, connection, ofp):
    Event.__init__(self)
    self.connection = connection
    self.ofp = ofp
    self.dpid = connection.dpid
    """
    xid: 
    ID da transação associado a este pacote.
    Respostas usar o mesmo ID como era no pedido
    para facilitar o emparelhamento
    """
    self.xid = ofp.xid 

class ConnectionIn (Event):
  def __init__ (self, connection):
    super(ConnectionIn,self).__init__()
    self.connection = connection
    self.dpid = connection.dpid
    self.nexus = None

"""
Determina que OpenFlowNexus fica o interruptor .
  implementação padrão sempre apenas dá a core.openflow
"""
class OpenFlowConnectionArbiter (EventMixin):
  
  _eventMixin_events = set([
    ConnectionIn,
  ])
  def __init__ (self, default = False):
    """ default as False causes it to always use core.openflow """
    self._default = default
    self._fallback = None

  def getNexus (self, connection):
    e = ConnectionIn(connection)
    self.raiseEventNoErrors(e)
    if e.nexus is None:
      e.nexus = self._default
    if e.nexus is False:
      if self._fallback is None:
        try:
          from pox.core import core
          self._fallback = core.openflow
        except:
          raise RuntimeError("No OpenFlow nexus for new connection")
      e.nexus = self._fallback
    return e.nexus


class ConnectionDict (dict):
  
  "iter: Este método é chamado quando uma iteração é necessário para um recipiente. "
  "Este método deve retornar um novo objeto iterador que pode iterar sobre todos os objetos no recipiente. "
  "Para mapeamentos, deve iterar sobre as chaves do recipiente, e também deve ser disponibilizado como o método iterkeys()."
  "Objetos Iterator também precisa implementar este método; eles são obrigados a voltar-se."
  
  def __iter__ (self):
    return self.itervalues()

    """
    Chamado para implementar operadores de teste de adesão. 
    Deve retornar true se item de está em auto , caso contrário false. 
    Para objetos de mapeamento, este deve considerar as chaves do mapeamento, 
    em vez de os valores ou os pares chave-item.

    Para objetos que não definem __contains__(), 
    o teste de associação tenta primeiro iteração via __iter__(), 
    em seguida, o antigo protocolo sequência iteração via __getitem__(). 
    """

  def __contains__ (self, item):
    
    "dict: Retornar um novo dict ionary inicializada a partir de um argumento opcional e um conjunto possivelmente vazio de argumentos."
    v = dict.__contains__(self, item)
    if v: return v
    return item in self.values()

  @property
  def dpids (self):
    return self.keys()

  def iter_dpids (self):
    return self.iterkeys()

"""
Principal ponto de interação OpenFlow .

  Geralmente, há apenas uma instância dessa classe , registrado como
  core.openflow . A maioria dos eventos OpenFlow fogo aqui, além de em seu
  ligações específicas .
"""
class OpenFlowNexus (EventMixin):

  _eventMixin_events = set([
    ConnectionUp,
    ConnectionDown,
    #"""
    #Features: O controlador pode solicitar a identidade e as capacidades básicas de um switch através do envio
    #um pedido de recursos ; o interruptor deve responder com uma características responder que especifica a identidade e básico
    #capacidades da chave. Isto é comumente realizada mediante estabelecimento do canal OpenFlow .
    #"""
    FeaturesReceived,
    #"""
    #Port- status: informar o controlador de uma mudança em uma porta . O interruptor é esperado para enviar porta -status
    #mensagens para os controladores como configuração da porta ou alterações Estado do porto. Estes eventos incluem mudança de
    #eventos de configuração de porta , por exemplo, se ele foi trazido para baixo diretamente por um usuário , e mudança de estado da porta
    #eventos , por exemplo, se a ligação caiu.
    #"""
    PortStatus,
    #"""
    #Fluxo - Removido : informar o controlador sobre a remoção de uma entrada de fluxo de uma tabela de fluxo. Fluxo-
    #mensagens removidas são enviados apenas para as entradas de fluxo com a flag OFPFF_SEND_FLOW_REM . Eles são
    #gerados como resultado de um fluxo controlador excluir pedido ou o fluxo de processo de termo interruptor quando um de
    #o tempo limite de fluxo for excedido
    #"""
    FlowRemoved,
    #"""
    #Packet -in : transferir o controlo de um pacote para o controlador . Para todos os pacotes enviados para o controlador
    #porta reservada usando uma entrada de fluxo ou a entrada de fluxo de mesa -miss , um evento pacote -in é sempre
    #enviado aos controladores. Outros processamento , tais como a verificação de TTL , também pode gerar pacotes -in eventos
    #para enviar pacotes para o controlador.
    #"""
    PacketIn,
    #"""
    #Barreira : Barreira de solicitação / resposta mensagens são utilizados pelo controlador para garantir dependências de mensagens
    #foram cumpridos ou para receber notificações de operações concluídas .
    #"""
    BarrierIn,
    ErrorIn,
    RawStatsReply,
    SwitchDescReceived,
    #"estatísticas do fluxo recebido"
    FlowStatsReceived,
    #"estatísticas de fluxos agregados"
    AggregateFlowStatsReceived,
    #"estatísticas da tabela recebida"
    TableStatsReceived,
    #"estatísticas da porta recebida"
    PortStatsReceived,
    #"estatísticas da filamrecebida"
    QueueStatsReceived,
    FlowRemoved,
  ])

  "Bytes para enviar ao controlador quando um pacote perde todos os fluxos"
  miss_send_len = of.OFP_DEFAULT_MISS_SEND_LEN

  "Activar / Desactivar compensação dos fluxos o interruptor ligar"
  clear_flows_on_connect = True

  def __init__ (self):
    self._connections = ConnectionDict() # DPID -> Connection

    from pox.core import core

    self.listenTo(core)

  @property
  def connections (self):
    return self._connections

  "Obter o objeto de conexão associado a um DPID ."
  def getConnection (self, dpid):
  
    return self._connections.get(dpid, None)

  "Enviar dados para um DPID específico."
  def sendToDPID (self, dpid, data):

    if dpid in self._connections:
      self._connections[dpid].send(data)
      return True
    else:
      import logging
      log = logging.getLogger("openflow")
      log.warn("Couldn't send to %s because we're not connected to it!" %
               (dpidToStr(dpid),))
      return False

  "controla o evento de baixo"
  def _handle_DownEvent (self, event):
    for c in self._connections.values():
      try:
        c.disconnect()
      except:
        pass

  "conectar"
  def _connect (self, con):
    self._connections[con.dpid] = con

  "desconectar"
  def _disconnect (self, dpid):
    if dpid in self._connections:
      del self._connections[dpid]
      return True
    return False

"iniciar (lançar)"
def launch (default_arbiter=True):
  from pox.core import core
  if core.hasComponent("openflow"):
    return
  if default_arbiter:
    core.registerNew(OpenFlowConnectionArbiter)
  core.register("openflow", OpenFlowNexus())
