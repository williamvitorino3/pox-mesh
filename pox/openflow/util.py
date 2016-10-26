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

import pox.openflow.libopenflow_01 as of
import struct
from pox.lib.revent import EventMixin
import pox.openflow

def make_type_to_unpacker_table ():
  """
  Returns a list of unpack methods.

  The resulting list maps OpenFlow types to functions which unpack
  data for those types into message objects.
  """

  "Retorna uma lista de métodos de descompactação ."

  "A lista resultante mapeia tipos OpenFlow para funções que desempacotar"
  "dados para esses tipos em objetos de mensagens."

  "max: Devolver o maior item em um iterable ou o maior dos dois ou mais argumentos."

 "Se um argumento posicional é fornecido, iterable deve ser um iterable não vazio "
 "(como uma string não-vazia, tupla ou lista)."
 "O maior item na iterable é retornado. Se dois ou mais argumentos posicionais são fornecidos, o maior dos argumentos posicionais é retornado."
 top = max(of._message_type_to_class)


  r = [of._message_type_to_class[i].unpack_new for i in range(0, top)]

  return r

"mensagens estirpes OpenFlow por DPID"
class DPIDWatcher (EventMixin):
  """
  Strains OpenFlow messages by DPID
  """

  #TODO: Reference count handling

  _eventMixin_events = pox.openflow.OpenFlowNexus._eventMixin_events

  def __init__ (self, dpid, nexus = None, invert = False):

    if nexus is None:
      from pox.core import core
      nexus = core.openflow

    self.invert = invert

    self._dpids = set()

    """ isinstance: Retorna verdadeiro se o objeto argumento é uma instância da ClassInfo argumento, 
    ou de um (direta, indireta ou virtual subclasse) da mesma. 
    Também retornar verdadeiro se ClassInfo é um objeto tipo (classe de estilo novo) 
    e objeto é um objeto desse tipo ou de um (direta, indireta ou virtual subclasse) da mesma. 
    Se objeto não é uma instância de classe ou um objeto do tipo de dado, a função sempre retorna false. 
    Se ClassInfo é uma tupla de classe ou objetos de tipo (ou de forma recursiva, outras linhas), 
    retornar true se objeto é uma instância de qualquer uma das classes ou tipos. 
    Se ClassInfo não é uma classe, tipo ou Conjunto de classes, tipos e tais tuplas, uma TypeErrorexceção é gerada.
    """
    if isinstance(dpid, str):
      dpid = dpid.replace(',',' ')
      dpid = dpid.split()
    if isinstance(dpid, (list,tuple)):
      for d in dpid:
        self._add_dpid(d)
    else:
      self._add_dpid(dpid)

    #core.listen_to_dependencies(self)

    for ev in self._eventMixin_events:
      nexus.addListener(ev, self._handler)

  def _handler (self, event, *args, **kw):
    "Devolver o valor do atributo com o nome do objeto ."
    "Nome deve ser uma cadeia. Se a string é o nome de um dos atributos do objeto, o resultado é o valor desse atributo."
    dpid = getattr(event, 'dpid', None)
    if dpid is None:
      return

    if self.invert:
      if event.dpid in self._dpids: return
    else:
      if event.dpid not in self._dpids: return

    if len(args) or len(kw):
      log.warn("Custom invoke for %s", event)
      # This is a warning because while I think this will always or almost
      # always work, I didn't feel like checking.

    self.raiseEventNoErrors(event)

  def _add_dpid (self, dpid):
    if dpid is True:
      # Special case -- everything!
      self._dpids = True
      return
    elif self._dpids is True:
      self._dpids = set()
    try:
      dpid = int(dpid)
    except:
      dpid = str_to_dpid(dpid)
    self._dpids.add(dpid)
