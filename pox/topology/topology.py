# Copyright 2011 James McCauley
#
# This file is part of POX.
#
# POX is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# POX is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with POX.  If not, see <http://www.gnu.org/licenses/>.

"""
O módulo de topologia é a raiz de um modelo de objeto composto por
entidades como switches, hosts, ligações, etc. Esse modelo de objeto
é preenchido por outros módulos. Por exemplo, o openflow.topology
preenche o objeto de topologia com switches OpenFlow.

Note que isso significa que muitas vezes você deseja invocar algo como:
  $ ./pox.py topology openflow.discovery openflow.topology
"""

"""
The Topology module is the root of an object model composed of entities
like switches, hosts, links, etc.  This object model is populated by other
modules.  For example, openflow.topology populates the topology object
with OpenFlow switches.

Note that this means that you often want to invoke something like:
   $ ./pox.py topology openflow.discovery openflow.topology
"""

from pox.lib.revent import *
from pox.core import core
from pox.lib.addresses import *
import traceback

import pickle


class EntityEvent (Event):
  def __init__ (self, entity):
    Event.__init__(self)
    self.entity = entity

class EntityJoin (EntityEvent):
  """
  Foi adicionada uma entidade.

  Observe que, se houver um evento de associação mais específico definido
  para uma entidade específica (por exemplo, Alternar a associação), este
  evento não será acionado.

  FAZER: ou nós poderíamos sempre levantar Entity Joins juntamente com Switch Joins,
  o que parece mais intuitivo para mim.
  """
  """
  An entity has been added.

  Note that if there is a more specific join event defined for a particular
  entity, (e.g., SwitchJoin), this event will not be fired.

  TODO: or we could always raise EntityJoins along with SwitchJoins, which
  seems more intuitive to me.
  """
  pass

class EntityLeave (EntityEvent):
  """
  Foi removida uma entidade.

  Observe que, se houver um evento de associação mais específico definido
  para uma entidade específica (por exemplo, Alternar a associação), este
  evento não será acionado.

  PARA FAZER: ou nós poderíamos sempre levantar Folhas de Entidade(EntityLeaves)
  juntamente com Folhas de Comutação(SwitchesLeaves), o que parece mais
  intuitivo para mim.
  """
  """
  An entity has been removed

  Note that if there is a more specific leave event defined for a particular
  entity, (e.g., SwitchLeave), this event will not be fired.

  TODO: or we could always raise EntityLeaves along with SwitchLeaves, which
  seems more intuitive to me.
  """
  pass

class SwitchEvent (EntityEvent): pass

class SwitchJoin (SwitchEvent):
  """
  Ao contrário de ConnectionUp, SwitchJoin ocorre em escalas de tempo
  grandes (por exemplo, um administrador movendo fisicamente um switch).
  """
  """
  As opposed to ConnectionUp, SwitchJoin occurs over large time scales
  (e.g. an administrator physically moving a switch).
  """
  def __init__ (self, switch):
    SwitchEvent.__init__(self, switch)
    self.switch = switch

class SwitchLeave (SwitchEvent):
  """
  Ao contrário de ConnectionDown, SwitchJoin ocorre em escalas de tempo
  grandes (por exemplo, um administrador movendo fisicamente um switch).
  """
  """
  As opposed to ConnectionDown, SwitchLeave occurs over large time scales
  (e.g. an administrator physically moving a switch).
  """
  pass

class SwitchConnectionUp(SwitchEvent):
  """
  Representa um lançamento de conexão uma nova conexão wm um switch.
  """
  def __init__(self, switch, connection):
    SwitchEvent.__init__(self, switch)
    self.switch = switch
    self.connection = connection

class SwitchConnectionDown(SwitchEvent): pass

class HostEvent (EntityEvent): pass
class HostJoin (HostEvent): pass
class HostLeave (HostEvent): pass

class Update (Event):
  """
  Chamado por topologia sempre que algo muda.
  """
  def __init__ (self, event=None):
    Event.__init__(self)
    self.event = event

class Entity (object):
  """
  Observe que a classe Entity é intencionalmente simples; Ele só serve
  como um tipo conveniente SuperClass.

  Cabe às subclasses implementar funcionalidade específica (p.
  Funcionalidade de comutador OpenFlow1.0). O objetivo desta decisão de
  design é impedir que detalhes específicos do protocolo sejam divulgados
  neste módulo... Mas esta decisão de design / não / implica que pox.topology
  serve para definir uma interface genérica para tipos de entidade abstrata.
  """
  """
  Note that the Entity class is intentionally simple; It only serves as a
  convenient SuperClass type.

  It's up to subclasses to implement specific functionality (e.g.
  OpenFlow1.0 switch functionality).  The purpose of this design decision
  is to prevent protocol specific details from being leaked into this
  module... but this design decision does /not/ imply that pox.toplogy
  serves to define a generic interface to abstract entity types.

  NOTE: /all/ subclasses must call this superconstructor, since
        the unique self.id is field is used by Topology
  """
  # This is a counter used so that we can get unique IDs for entities.
  # Some entities don't need this because they have more meaningful
  # identifiers.
  _next_id = 101
  _all_ids = set()
  _tb = {}

  def __init__ (self, id=None):
    if id:
      if id in Entity._all_ids:
        print("".join(traceback.format_list(self._tb[id])))
        raise Exception("ID %s already taken" % str(id))
    else:
      while Entity._next_id in Entity._all_ids:
        Entity._next_id += 1
      id = Entity._next_id

    self._tb[id] = traceback.extract_stack()
    Entity._all_ids.add(id)
    self.id = id

  def serialize(self):
    return pickle.dumps(self, protocol = 0)

  @classmethod
  def deserialize(cls):
    return pickle.loads(cls, protocol = 0)

class Host (Entity):
  """
  Entidade genérica de Host.
  """
  """
  A generic Host entity.
  """
  def __init__(self,id=None):
    Entity.__init__(self, id)

class Switch (Entity):
  """
  Subclasse por classes de comutação específicas do protocolo,
  por exemplo. Pox.openflow.topology.OpenFlowSwitch.
  """
  """
  Subclassed by protocol-specific switch classes,
  e.g. pox.openflow.topology.OpenFlowSwitch;
  """
  def __init__(self, id=None):
    # Switches often have something more meaningful to use as an ID
    # (e.g., a DPID or MAC address), so they take it as a parameter.
    Entity.__init__(self, id)

class Port (Entity):
  """
  Representação da porta de um Switch.
  """
  def __init__ (self, num, hwAddr, name):
    Entity.__init__(self)
    self.number = num
    self.hwAddr = EthAddr(hwAddr)
    self.name = name

class Controller (Entity):
  """
  Representação de um controlador.
  """
  def __init__(self, name, handshake_complete=False):
    self.id = name
    # TODO: python aliases?
    self.name = name
    self.handshake_complete = handshake_complete

  def handshake_completed(self):
    self.handshake_complete = True

class Topology (EventMixin):
  """
  Classe que implemente a Topologia.
  """

  # Lista de eventos.
  _eventMixin_events = [
    SwitchJoin,
    SwitchLeave,
    HostJoin,
    HostLeave,
    EntityJoin,
    EntityLeave,

    Update
  ]

  _core_name = "topology" # We want to be core.topology

  def __init__ (self, name="topology"):
    EventMixin.__init__(self)
    self._entities = {}
    self.name = name
    self.log = core.getLogger(name)

    # If a client registers a handler for these events after they have
    # already occurred, we promise to re-issue them to the newly joined
    # client.
    self._event_promises = {
      SwitchJoin : self._fulfill_SwitchJoin_promise
    }

  def getEntityByID (self, ID, fail=False):
    """
    Gera uma exceção se a falha for True ea entidade não existir
    Consulte também: A propriedade 'entity'.
    :param ID: Identificador da entidade.
    :param fail: Valor da falha.
    :return: Posição da lista de entidades.
    """
    """
    Raises an exception if fail is True and the entity doesn't exist
    See also: The 'entity' property.
    """
    if fail:
      return self._entities[ID]
    else:
      return self._entities.get(ID, None)

  def removeEntity (self, entity):
    """
    Remove entidade da lista de entidades.

    :param entity: Entidade à ser removida.
    :return: Sem retorno.
    """
    del self._entities[entity.id]
    self.log.info(str(entity) + " left")
    if isinstance(entity, Switch):
      self.raiseEvent(SwitchLeave, entity)
    elif isinstance(entity, Host):
      self.raiseEvent(HostLeave, entity)
    else:
      self.raiseEvent(EntityLeave, entity)

  def addEntity (self, entity):
    """
    Adiciona entidade na lista de entidades.
    :param entity: Entidade à ser adicionada.
    :return: Sem retorno.
    """
    """ Will raise an exception if entity.id already exists """
    if entity.id in self._entities:
      raise RuntimeError("Entity exists")
    self._entities[entity.id] = entity
    self.log.debug(str(entity) + " (id: " + str(entity.id) + ") joined")
    if isinstance(entity, Switch):
      self.raiseEvent(SwitchJoin, entity)
    elif isinstance(entity, Host):
      self.raiseEvent(HostJoin, entity)
    else:
      self.raiseEvent(EntityJoin, entity)

  def getEntitiesOfType (self, t=Entity, subtypes=True):
    """
    Cria uma Lista de entidades com o tipo correspondente as de 't'.
    :param t: Entidade à ser utilizada como padrão.
    :param subtypes: Verificação de sub tipos.
    :return:  Lista de entidades correspondentes à 't'.
    """
    if subtypes is False:
      return [x for x in self._entities.itervalues() if type(x) is t]
    else:
      return [x for x in self._entities.itervalues() if isinstance(x, t)]

  def addListener(self, eventType, handler, once=False, weak=False,
                  priority=None, byName=False):
    """
    Interagimos no EventMixin.addListener para verificar se o eventType
    está na nossa lista de promessas. Em caso afirmativo, ative o
    manipulador para todos os eventos acionados anteriormente.

    :param eventType: Objeto de classe de evento (por exemplo, ConnectionUp).
    Se byName for True, deve ser uma string (por exemplo, "ConnectionUp").

    :param handler: Função / método a ser invocado quando o evento é levantado.

    :param once:  Se verdadeiro, este manipulador é removido após a primeira vez que é acionado.

    :param weak:  Se o manipulador for um método no objeto A,
      então ouvir um evento no objeto B normalmente fará B ter
      uma referência a A, então A não pode ser liberado até
      que B seja liberado ou o ouvinte seja removido.
      Se weak for True, não há relação entre as vidas do editor e do assinante.

    :param priority:  A ordem em que chamar manipuladores de eventos
      se houver múltiplos para um tipo de evento. Deve provavelmente ser
      um número inteiro, onde maior significa chamá-lo mais cedo.
      Não especifique se você não se importa.

    :param byName: Verdadeiro se eventType for um nome de string,
      senão é uma subclasse Event.

    :return: Tupla contendo o tipo do evento e o ID do evento.
    """
    """
    We interpose on EventMixin.addListener to check if the eventType is
    in our promise list. If so, trigger the handler for all previously
    triggered events.
    """
    if eventType in self._event_promises:
      self._event_promises[eventType](handler)

    return EventMixin.addListener(self, eventType, handler, once=once,
                                  weak=weak, priority=priority,
                                  byName=byName)

  # Parei aqui...
  def raiseEvent (self, event, *args, **kw):
    """
    Whenever we raise any event, we also raise an Update, so we extend
    the implementation in EventMixin.
    """
    rv = EventMixin.raiseEvent(self, event, *args, **kw)
    if type(event) is not Update:
      EventMixin.raiseEvent(self, Update(event))
    return rv

  def serialize (self):
    """
    Picklize our current entities.

    Returns a hash: { id -> pickled entitiy }
    """
    id2entity = {}
    for id in self._entities:
      entity = self._entities[id]
      id2entity[id] = entity.serialize()
    return id2entity

  def deserializeAndMerge (self, id2entity):
    """
    Given the output of topology.serialize(), deserialize each entity, and:
      - insert a new Entry if it didn't already exist here, or
      - update a pre-existing entry if it already existed
    """
    for entity_id in id2entity.keys():
      pickled_entity = id2entity[entity_id].encode('ascii', 'ignore')
      entity = pickle.loads(pickled_entity)
      entity.id = entity_id.encode('ascii', 'ignore')
      try:
        # Try to parse it as an int
        entity.id = int(entity.id)
      except ValueError:
        pass

      existing_entity = self.getEntityByID(entity.id)
      if existing_entity:
        self.log.debug("New metadata for %s: %s " % (str(existing_entity), str(entity)))
        # TODO: define an Entity.merge method (need to do something about his update!)
      else:
        self.addEntity(entity)

  def _fulfill_SwitchJoin_promise(self, handler):
    """ Trigger the SwitchJoin handler for all pre-existing switches """
    for switch in self.getEntitiesOfType(Switch, True):
      handler(SwitchJoin(switch))

  def __len__(self):
    return len(self._entities)

  def __str__(self):
    # TODO: display me graphically
    strings = []
    strings.append("topology (%d total entities)" % len(self._entities))
    for id,entity in self._entities.iteritems():
      strings.append("%s %s" % (str(id), str(entity)))

    return '\n'.join(strings)
