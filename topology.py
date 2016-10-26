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
O OpenFlow não sabe nada sobre topologia , e Topologia não
sabe nada sobre OpenFlow . Este módulo sabe algo sobre ambos,
e conecta os dois juntos.

Especificamente , este módulo é um pouco como um adaptador que escuta
eventos de outras partes do substem openflow (tais como a descoberta ) , e
usa -los para preencher e manipular Topologia.
"""

import itertools

from pox.lib.revent import *
import libopenflow_01 as of
from pox.openflow import *
from pox.core import core
from pox.topology.topology import *
from pox.openflow.discovery import *
from pox.openflow.libopenflow_01 import xid_generator
from pox.openflow.flow_table import FlowTable,FlowTableModification,TableEntry
from pox.lib.util import dpidToStr
from pox.lib.addresses import *

import pickle
import itertools

"""
Depois de interruptor desliga , tem esta quantidade de segundos para se reconectar no
Fim de reativar o mesmo objeto OpenFlowSwitch . Depois disso, se
Ele se reconecta , será um novo objeto de switch.
"""
RECONNECT_TIMEOUT = 30

log = core.getLogger()

class OpenFlowTopology (object):

 "Ouve vários eventos específicos do OpenFlow e usa aqueles para manipular"
  "Topologia em conformidade."

  def __init__ (self):
    core.listen_to_dependencies(self, ['topology'], short_attrs=True)


 "O módulo de descoberta simplesmente envia pacotes LLDP e gatilhos"
    "LinkEvents para interruptores descobertos . É o nosso trabalho para tirar esses"
    "LinkEvents e atualização pox.topology ."

     def _handle_openflow_discovery_LinkEvent (self, event):

    link = event.link
    sw1 = self.topology.getEntityByID(link.dpid1)
    sw2 = self.topology.getEntityByID(link.dpid2)
    if sw1 is None or sw2 is None: return
    if link.port1 not in sw1.ports or link.port2 not in sw2.ports: return
    if event.added:
      sw1.ports[link.port1].addEntity(sw2, single=True)
      sw2.ports[link.port2].addEntity(sw1, single=True)
    elif event.removed:
      sw1.ports[link.port1].entities.discard(sw2)
      sw2.ports[link.port2].entities.discard(sw1)

"Lida com a conexão 'de cima' do openflow"
  def _handle_openflow_ConnectionUp (self, event):
    sw = self.topology.getEntityByID(event.dpid)
    add = False
    if sw is None:
      sw = OpenFlowSwitch(event.dpid)
      add = True
    else:
      if sw._connection is not None:
        log.warn("Switch %s connected, but... it's already connected!" %
                 (dpidToStr(event.dpid),))
    sw._setConnection(event.connection, event.ofp)
    log.info("Switch " + dpidToStr(event.dpid) + " connected")
    if add:
      self.topology.addEntity(sw)
      sw.raiseEvent(SwitchJoin, sw)

  "Lida com a conexão 'de baixo' do openflow"
  def _handle_openflow_ConnectionDown (self, event):
    sw = self.topology.getEntityByID(event.dpid)
    if sw is None:
      log.warn("Switch %s disconnected, but... it doesn't exist!" %
               (dpidToStr(event.dpid),))
    else:
      if sw._connection is None:
        log.warn("Switch %s disconnected, but... it's wasn't connected!" %
                 (dpidToStr(event.dpid),))
      sw._connection = None
      log.info("Switch " + str(event.dpid) + " disconnected")

  """
  Uma subclasse de topology.Port para portas de switch OpenFlow .

  Acrescenta a noção de " entidades ligadas " , que o padrão
  classe ofp_phy_port não tem .

  Nota: Não usado atualmente .
  """
class OpenFlowPort (Port):
  
  def __init__ (self, ofp):
    # Passed an ofp_phy_port
    Port.__init__(self, ofp.port_no, ofp.hw_addr, ofp.name)
    self.isController = self.number == of.OFPP_CONTROLLER "OFPP_CONTROLLER: Enviar para o controlador."
    self._update(ofp)
    self.exists = True
    self.entities = set()

 "atualiza"
  def _update (self, ofp):
    "Campos da struct ofp_port: name, port_no, hw_addr, config, state"
    assert self.name == ofp.name
    assert self.number == ofp.port_no
    self.hwAddr = EthAddr(ofp.hw_addr)
    self._config = ofp.config
    self._state = ofp.state

  "contains: Chamado para implementar operadores de teste de adesão"
  def __contains__ (self, item):
    "Verdadeiro se essa porta se conecta à entidade especificada."
    return item in self.entities

  def addEntity (self, entity, single = False):
    # Invariant (not currently enforced?):
    #   len(self.entities) <= 2  ?
    if single:
      self.entities = set([entity])
    else:
      self.entities.add(entity)

  """
  A ofp_phy_port fornecido
  estrutura descreve o comportamento do interruptor através do seu campo de bandeiras . No entanto, é possível que o
  controlador deseja mudar uma bandeira especial e pode não saber o status atual de todas as bandeiras . 
  """
  def to_ofp_phy_port(self):
    return of.ofp_phy_port(port_no = self.number, hw_addr = self.hwAddr,
                           name = self.name, config = self._config,
                           state = self._state)

"Retorna uma string contendo uma representação de impressão de um objeto. "
  def __repr__ (self):
    return "<Port #" + str(self.number) + ">"


"""
  OpenFlowSwitches são entidades topologia ( herdam topology.Switch )

  OpenFlowSwitches são persistentes ; isto é, se um interruptor reconecta , o
  campo de conexão do objeto OpenFlowSwitch inicial será simplesmente
  repor para referir a nova ligação .

  Por enquanto, OpenFlowSwitch é essencialmente um proxy para sua conexão subjacente
  objeto. Mais tarde , vamos , possivelmente, adicionar operações mais explícitos o cliente pode
  realizar .

  Observe que, para efeitos do depurador , podemos interpor em
  uma entidade interruptor enumerando todos os ouvintes para os eventos listados
  abaixo , e desencadeando eventos simulados para os ouvintes.
"""
class OpenFlowSwitch (EventMixin, Switch):
  
  _eventMixin_events = set([
    SwitchJoin, # Defined in pox.topology
    SwitchLeave,
    SwitchConnectionUp,
    SwitchConnectionDown,

    PortStatus, # Defined in libopenflow_01
    FlowRemoved,
    PacketIn,
    BarrierIn,
  ])

  def __init__ (self, dpid):
    if not dpid:
      raise AssertionError("OpenFlowSwitch should have dpid")

    Switch.__init__(self, id=dpid)
    EventMixin.__init__(self)
    self.dpid = dpid
    self.ports = {}
    self.flow_table = OFSyncFlowTable(self)
    self.capabilities = 0
    self._connection = None
    self._listeners = []
    self._reconnectTimeout = None # Timer for reconnection
    self._xid_generator = xid_generator( ((dpid & 0x7FFF) << 16) + 1)

  "estabelece a conexão"
  def _setConnection (self, connection, ofp=None):
    ''' ofp - a FeaturesReply message '''
    if self._connection: self._connection.removeListeners(self._listeners)
    self._listeners = []
    self._connection = connection
    if self._reconnectTimeout is not None:
      self._reconnectTimeout.cancel()
      self._reconnectTimeout = None
    if connection is None:
      self._reconnectTimeout = Timer(RECONNECT_TIMEOUT,
                                     self._timer_ReconnectTimeout)
    if ofp is not None:
      # update capabilities
      self.capabilities = ofp.capabilities
      # update all ports
      untouched = set(self.ports.keys())
      for p in ofp.ports:
        if p.port_no in self.ports:
          self.ports[p.port_no]._update(p)
          untouched.remove(p.port_no)
        else:
          self.ports[p.port_no] = OpenFlowPort(p)
      for p in untouched:
        self.ports[p].exists = False
        del self.ports[p]
    if connection is not None:
      self._listeners = self.listenTo(connection, prefix="con")
      self.raiseEvent(SwitchConnectionUp(switch = self,
                                         connection = connection))
    else:
      self.raiseEvent(SwitchConnectionDown(self))

  "Chamado se tivéssemos sido desligada por alguns segundos RECONNECT_TIMEOUT "
  def _timer_ReconnectTimeout (self):
    self._reconnectTimeout = None
    core.topology.removeEntity(self)
    self.raiseEvent(SwitchLeave, self)

  def _handle_con_PortStatus (self, event):
    p = event.ofp.desc
    if event.ofp.reason == of.OFPPR_DELETE: "O valor indica a razão OFPPR_DELETE uma porta que tenha sido removido a partir do caminho de dados , e não mais existe."
      if p.port_no in self.ports:
        self.ports[p.port_no].exists = False
        del self.ports[p.port_no]
    elif event.ofp.reason == of.OFPPR_MODIFY: "O valor razão OFPPR_MODIFY denota um porto que estado ou configuração mudou"
      self.ports[p.port_no]._update(p)
    else:
      assert event.ofp.reason == of.OFPPR_ADD "O valor razão OFPPR_ADD denota uma porta que não existia no caminho de dados e foi adicionado. "
      assert p.port_no not in self.ports
      self.ports[p.port_no] = OpenFlowPort(p)
    self.raiseEvent(event)
    event.halt = False

  "Controla a conexão 'baixa'"
  def _handle_con_ConnectionDown (self, event):
    self._setConnection(None)

  "Controla o pacote de 'dentro'"
  def _handle_con_PacketIn (self, event):
    self.raiseEvent(event)
    event.halt = False

  "Controla a barreira de dentro"
  def _handle_con_BarrierIn (self, event):
    self.raiseEvent(event)
    event.halt = False

  "Controla o fluxo removido"
  def _handle_con_FlowRemoved (self, event):
    self.raiseEvent(event)
    self.flowTable.removeFlow(event)
    event.halt = False

  "Encontra a porta de entidade"
  def findPortForEntity (self, entity):
    for p in self.ports.itervalues():
      if entity in p:
        return p
    return None

  @property
  def connected(self):
    return self._connection != None

  "fluxo de instalação na tabela local e a chave associada"
  def installFlow(self, **kw):
    self.flow_table.install(TableEntry(**kw))

  "Avanço sobre dados não- serializado , por exemplo, soquetes"
  def serialize (self):
    serializable = OpenFlowSwitch(self.dpid)
    return pickle.dumps(serializable, protocol = 0)

  "Envia"
  def send(self, *args, **kw):
    return self._connection.send(*args, **kw)

  "Lê"
  def read(self, *args, **kw):
   return self._connection.read(*args, **kw)

  def __repr__ (self):
    return "<%s %s>" % (self.__class__.__name__, dpidToStr(self.dpid))

  @property
  def name(self):
    return repr(self)

"A tabela de fluxo que mantém em sincronia com um interruptor"
class OFSyncFlowTable (EventMixin):
  _eventMixin_events = set([FlowTableModification])
  """
  Openflow flow modification: ofp_flow_mod_command
  OFPFC_ADD: Novo fluxo 
  OFPFC_DELETE: Excluir todos os fluxos correspondentes .
  OFPFC_DELETE_STRICT: Excluir entrada estritamente wildcards correspondentes e prioridade.
  """
  ADD = of.OFPFC_ADD
  REMOVE = of.OFPFC_DELETE
  REMOVE_STRICT = of.OFPFC_DELETE_STRICT
  TIME_OUT = 2

  def __init__ (self, switch=None, **kw):
    EventMixin.__init__(self)
    self.flow_table = FlowTable()
    self.switch = switch

    "uma lista de pendentes entradas de tabela de fluxo : tuplas (ADD | REMOVER , a entrada )"
    self._pending = []

    "um mapa das barreiras pendentes barrier_xid- > ( [ entry1 , entry2 ] )"
    self._pending_barrier_to_ops = {}

    self._pending_op_to_barrier = {}

    self.listenTo(switch)

  """
  de forma assíncrona instalar entradas na tabela de fluxo

  levantará um evento FlowTableModification quando a mudança foi
  processados ​​pelo comutador
  """
  def install (self, entries=[]):
    
    self._mod(entries, OFSyncFlowTable.ADD)

  """
    de forma assíncrona remover entradas na tabela de fluxo

    levantará um evento FlowTableModification quando a mudança foi
    processados ​​pelo comutador
  """
  def remove_with_wildcards (self, entries=[]):
  
    self._mod(entries, OFSyncFlowTable.REMOVE)

  """
    assincronamente remover entradas na tabela de fluxo .

    levantará um evento FlowTableModification quando a mudança foi
    processados ​​pelo comutador
  """
  def remove_strict (self, entries=[]):
    self._mod(entries, OFSyncFlowTable.REMOVE_STRICT)

  "property: retornar uma propriedade de atributo para novo estilo de classe es (classes que derivam object)."
  @property
  def entries (self):
    return self.flow_table.entries

  @property
  def num_pending (self):
    return len(self._pending)

  "Len: Retorna o tamanho (número de itens) de um objeto (flow_table). "
  def __len__ (self):
    return len(self.flow_table)

  def _mod (self, entries, command):
    "isinstance: Retorna verdadeiro se o objeto argumento é uma instância da ClassInfo argumento, ou de um (direta, indireta ou virtual subclasse) da mesma."
    if isinstance(entries, TableEntry):
      entries = [ entries ]

    for entry in entries:
      if(command == OFSyncFlowTable.REMOVE):
        self._pending = [(cmd,pentry) for cmd,pentry in self._pending
                         if not (cmd == OFSyncFlowTable.ADD
                                 and entry.matches_with_wildcards(pentry))]
      elif(command == OFSyncFlowTable.REMOVE_STRICT):
        self._pending = [(cmd,pentry) for cmd,pentry in self._pending
                         if not (cmd == OFSyncFlowTable.ADD
                                 and entry == pentry)]

      self._pending.append( (command, entry) )

    self._sync_pending()

  def _sync_pending (self, clear=False):
    if not self.switch.connected:
      return False

    # resync the switch
    if clear:
      self._pending_barrier_to_ops = {}
      self._pending_op_to_barrier = {}
      self._pending = filter(lambda(op): op[0] == OFSyncFlowTable.ADD,
                             self._pending)

      self.switch.send(of.ofp_flow_mod(command=of.OFPFC_DELETE,
                                       match=of.ofp_match()))
      self.switch.send(of.ofp_barrier_request())

      todo = map(lambda(e): (OFSyncFlowTable.ADD, e),
                 self.flow_table.entries) + self._pending
    else:
      todo = [op for op in self._pending
              if op not in self._pending_op_to_barrier
              or (self._pending_op_to_barrier[op][1]
                  + OFSyncFlowTable.TIME_OUT) < time.time() ]

    for op in todo:
      fmod_xid = self.switch._xid_generator()
      flow_mod = op[1].to_flow_mod(xid=fmod_xid, command=op[0],
                                   flags=op[1].flags | of.OFPFF_SEND_FLOW_REM)
      "OFPFF_SEND_FLOW_REM: Enviar mensagem removido fluxo quando o fluxo. Expira ou é excluído."
      self.switch.send(flow_mod)

    barrier_xid = self.switch._xid_generator()
    self.switch.send(of.ofp_barrier_request(xid=barrier_xid))
    now = time.time()
    self._pending_barrier_to_ops[barrier_xid] = todo

    for op in todo:
      self._pending_op_to_barrier[op] = (barrier_xid, now)

  def _handle_SwitchConnectionUp (self, event):
    # sync all_flows
    self._sync_pending(clear=True)

  "CONEXÃO para baixo. muito ruim para nossos entradas não confirmados"
  def _handle_SwitchConnectionDown (self, event):
    self._pending_barrier_to_ops = {}
    self._pending_op_to_barrier = {}

  "tempo para sincronizar alguns destes fluxos"
  def _handle_BarrierIn (self, barrier):
    if barrier.xid in self._pending_barrier_to_ops:
      added = []
      removed = []
      #print "barrier in: pending for barrier: %d: %s" % (barrier.xid,
      #    self._pending_barrier_to_ops[barrier.xid])
      for op in self._pending_barrier_to_ops[barrier.xid]:
        (command, entry) = op
        if(command == OFSyncFlowTable.ADD):
          self.flow_table.add_entry(entry)
          added.append(entry)
        else:
          removed.extend(self.flow_table.remove_matching_entries(entry.match,
              entry.priority, strict=command == OFSyncFlowTable.REMOVE_STRICT))
        #print "op: %s, pending: %s" % (op, self._pending)
        if op in self._pending: self._pending.remove(op)
        self._pending_op_to_barrier.pop(op, None)
      del self._pending_barrier_to_ops[barrier.xid]
      self.raiseEvent(FlowTableModification(added = added, removed=removed))
      return EventHalt
    else:
      return EventContinue

  "processar um evento removido fluxo - remover o fluxo correspondente a partir da tabela ."
  def _handle_FlowRemoved (self, event):
    flow_removed = event.ofp
    for entry in self.flow_table.entries:
      if (flow_removed.match == entry.match
          and flow_removed.priority == entry.priority):
        self.flow_table.remove_entry(entry)
        self.raiseEvent(FlowTableModification(removed=[entry]))
        return EventHalt
    return EventContinue

"iniciar"
def launch ():
  if not core.hasComponent("openflow_topology"):
    core.register("openflow_topology", OpenFlowTopology())
