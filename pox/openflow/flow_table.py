# Copyright 2011,2012,2013 Colin Scott
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
Implementation of an OpenFlow flow table
"""

from libopenflow_01 import *

"pox.lib.revent: Biblioteca do POX que implementa eventos." 
"Todos eventos do POX são instâncias de sub-classes da classe Event;"
from pox.lib.revent import * 

import time
import math

# FlowTable Entries:
#   match - ofp_match (13-tuple)
#   counters - hash from name -> count. May be stale
#   actions - ordered list of ofp_action_*s to apply for matching packets
class TableEntry (object):
  """
  Models a flow table entry, with a match, actions, and options/flags/counters.

  Note: The current time can either be specified explicitely with the optional
        'now' parameter or is taken from time.time()
  """
  #def __init__(self, a, b):
   #     self.a = a
    #    self.b = b

    #def soma(self):
     #   return self.a + self.b"

  def __init__ (self, priority=OFP_DEFAULT_PRIORITY, cookie=0, idle_timeout=0,
                hard_timeout=0, flags=0, match=ofp_match(), actions=[],
                buffer_id=None, now=None): #começa com None, pois a instância foi criada mas ainda não foi salva.
    """
    Initialize table entry
    """
    if now is None: now = time.time()
    self.created = now
    self.last_touched = self.created
    self.byte_count = 0
    self.packet_count = 0
    self.priority = priority
    self.cookie = cookie
    self.idle_timeout = idle_timeout
    self.hard_timeout = hard_timeout
    self.flags = flags
    self.match = match
    self.actions = actions
    self.buffer_id = buffer_id

  "Retornar um método estático para a função ."
  "Componentes de uma entrada da tabela de fluxo"
  @staticmethod 
  def from_flow_mod (flow_mod):
    return TableEntry(priority=flow_mod.priority, 
                      cookie=flow_mod.cookie,
                      idle_timeout=flow_mod.idle_timeout,
                      hard_timeout=flow_mod.hard_timeout,
                      flags=flow_mod.flags,
                      match=flow_mod.match,
                      actions=flow_mod.actions,
                      buffer_id=flow_mod.buffer_id)

  def to_flow_mod (self, flags=None, **kw):
    if flags is None: flags = self.flags
    return ofp_flow_mod(priority=self.priority,
                        cookie=self.cookie,
                        match=self.match,
                        idle_timeout=self.idle_timeout,
                        hard_timeout=self.hard_timeout,
                        actions=self.actions,
                        buffer_id=self.buffer_id,
                        flags=flags, **kw)

  @property
  def effective_priority (self):
    """
    Exact matches effectively have an "infinite" priority
    """
    "Resultados exatos efetivamente têm uma prioridade 'infinita'"
    return self.priority if self.match.is_wildcarded else (1<<16) + 1

  def is_matched_by (self, match, priority=None, strict=False, out_port=None):
    """
    Tests whether a given match object matches this entry

    Used for, e.g., flow_mod updates

    If out_port is any value besides None, the the flow entry must contain an
    output action to the specified port.
    """
    match_a = lambda a: isinstance(a, ofp_action_output) and a.port == out_port
    port_matches = (out_port is None) or any(match_a(a) for a in self.actions)

    if strict:
      return port_matches and self.match == match and self.priority == priority
    else:
      return port_matches and match.matches_with_wildcards(self.match)

    "Atualiza informações desta entrada com base em encontrar um pacote."
    "Atualizações ambos os cumulativos dadas contagens de bytes de pacotes encontrados e o temporizador de validade."
    def touch_packet (self, byte_count, now=None):
      """
      Updates information of this entry based on encountering a packet.

      Updates both the cumulative given byte counts of packets encountered and
      the expiration timer.
      """

      if now is None: now = time.time()
      self.byte_count += byte_count
      self.packet_count += 1
      self.last_touched = now

  def is_idle_timed_out (self, now=None):
    if now is None: now = time.time()
    if self.idle_timeout > 0:
      if (now - self.last_touched) > self.idle_timeout:
        return True
    return False

  def is_hard_timed_out (self, now=None):
    if now is None: now = time.time()
    if self.hard_timeout > 0:
      if (now - self.created) > self.hard_timeout:
        return True
    return False

  "Testa se esta entrada de fluxo é expirado devido ao seu tempo limite de ociosidade ou disco."
  def is_expired (self, now=None):
    """
    Tests whether this flow entry is expired due to its idle or hard timeout
    """
    if now is None: now = time.time()
    return self.is_idle_timed_out(now) or self.is_hard_timed_out(now)

  "Retorna uma representação do objeto como str, usado em conversões para string."
  def __str__ (self):
    return type(self).__name__ + "\n  " + self.show()

  "Retorna uma representação do objeto usada para outros objetos"
  def __repr__ (self):
    return "TableEntry(" + self.show() + ")"

  def show (self):
    outstr = ''
    outstr += "priority=%s, " % self.priority
    outstr += "cookie=%x, " % self.cookie
    outstr += "idle_timeout=%d, " % self.idle_timeout
    outstr += "hard_timeout=%d, " % self.hard_timeout
    outstr += "match=%s, " % self.match
    outstr += "actions=%s, " % repr(self.actions)
    outstr += "buffer_id=%s" % str(self.buffer_id)
    return outstr

  def flow_stats (self, now=None):
    if now is None: now = time.time()
    dur_nsec,dur_sec = math.modf(now - self.created)
    return ofp_flow_stats(match=self.match,
                          duration_sec=int(dur_sec),
                          duration_nsec=int(dur_nsec * 1e9),
                          priority=self.priority,
                          idle_timeout=self.idle_timeout,
                          hard_timeout=self.hard_timeout,
                          cookie=self.cookie,
                          packet_count=self.packet_count,
                          byte_count=self.byte_count,
                          actions=self.actions)

 
  "TODO : Renomear flow_stats para to_flow_stats e refatorar "
  def to_flow_removed (self, now=None, reason=None):
    #TODO: Rename flow_stats to to_flow_stats and refactor?
    if now is None: now = time.time()
    dur_nsec,dur_sec = math.modf(now - self.created)
    fr = ofp_flow_removed()
    fr.match = self.match
    fr.cookie = self.cookie
    fr.priority = self.priority
    fr.reason = reason
    fr.duration_sec = int(dur_sec)
    fr.duration_nsec = int(dur_nsec * 1e9)
    fr.idle_timeout = self.idle_timeout
    fr.hard_timeout = self.hard_timeout
    fr.packet_count = self.packet_count
    fr.byte_count = self.byte_count
    return fr

"Razão para modificação."
"Atualmente, este é usado apenas para o afastamento e seja um dos OFPRR_x ,"" \
""Ou Nenhum se não se correlacionam com qualquer um dos itens da especificação ."

class FlowTableModification (Event):
  def __init__ (self, added=[], removed=[], reason=None):
    Event.__init__(self)
    self.added = added
    self.removed = removed

    # Reason for modification.
    # Presently, this is only used for removals and is either one of OFPRR_x,
    # or None if it does not correlate to any of the items in the spec.
    self.reason = reason

"modelo geral de uma tabela de fluxo."

"Mantém uma lista ordenada das entradas de fluxos , e encontra entradas correspondentes para"
"pacotes e outras entradas . Suporta expiração de fluxos ."

class FlowTable (EventMixin):
  """
  General model of a flow table.

  Maintains an ordered list of flow entries, and finds matching entries for
  packets and other entries. Supports expiration of flows.
  """
  _eventMixin_events = set([FlowTableModification])

  def __init__ (self):
    EventMixin.__init__(self)

    # Table is a list of TableEntry sorted by descending effective_priority.
    self._table = []

  def _dirty (self):
    """
    Call when table changes
    """
    pass

  @property
  def entries (self):
    return self._table

  def __len__ (self):
    return len(self._table)

  def add_entry (self, entry):
    "asset: Ajuda a encontrar erros mais facilmente"
    assert isinstance(entry, TableEntry)

    "Use a pesquisa binária para inserir no lugar correto"
    "Este é mais rápido , mesmo para tamanhos de mesa modestos , e muito, muito mais rápido"
    #self._table.append(entry)
    #self._table.sort(key=lambda e: e.effective_priority, reverse=True)

    # Use binary search to insert at correct place
    # This is faster even for modest table sizes, and way, way faster
    # as the tables grow larger.
    priority = entry.effective_priority
    table = self._table
    low = 0
    high = len(table)
    while low < high:
        middle = (low + high) // 2
        if priority >= table[middle].effective_priority:
          high = middle
          continue
        low = middle + 1
    table.insert(low, entry)

    self._dirty()

    self.raiseEvent(FlowTableModification(added=[entry]))

  def remove_entry (self, entry, reason=None):
    assert isinstance(entry, TableEntry)
    self._table.remove(entry)
    self._dirty()
    self.raiseEvent(FlowTableModification(removed=[entry], reason=reason))

  def matching_entries (self, match, priority=0, strict=False, out_port=None):
    "Lambda: lambdaé apenas uma maneira elegante de dizer function"
    entry_match = lambda e: e.is_matched_by(match, priority, strict, out_port)
    return [ entry for entry in self._table if entry_match(entry) ]

  def flow_stats (self, match, out_port=None, now=None):
    mc_es = self.matching_entries(match=match, strict=False, out_port=out_port)
    return [ e.flow_stats(now) for e in mc_es ]

  def aggregate_stats (self, match, out_port=None):
    mc_es = self.matching_entries(match=match, strict=False, out_port=out_port)
    packet_count = 0
    byte_count = 0
    flow_count = 0
    for entry in mc_es:
      packet_count += entry.packet_count
      byte_count += entry.byte_count
      flow_count += 1
    return ofp_aggregate_stats(packet_count=packet_count,
                               byte_count=byte_count,
                               flow_count=flow_count)

  def _remove_specific_entries (self, flows, reason=None):
    #for entry in flows:
    #  self._table.remove(entry)
    #self._table = [entry for entry in self._table if entry not in flows]
    if not flows: return
    self._dirty()
    remove_flows = set(flows)
    i = 0
    while i < len(self._table):
      entry = self._table[i]
      if entry in remove_flows:
        del self._table[i]
        remove_flows.remove(entry)
        if not remove_flows: break
      else:
        i += 1
    assert len(remove_flows) == 0
    self.raiseEvent(FlowTableModification(removed=flows, reason=reason))

  def remove_expired_entries (self, now=None):
    idle = []
    hard = []
    if now is None: now = time.time()
    for entry in self._table:
      if entry.is_idle_timed_out(now):
        idle.append(entry)
      elif entry.is_hard_timed_out(now):
        hard.append(entry)
    self._remove_specific_entries(idle, OFPRR_IDLE_TIMEOUT)
    self._remove_specific_entries(hard, OFPRR_HARD_TIMEOUT)

  def remove_matching_entries (self, match, priority=0, strict=False,
                               out_port=None, reason=None):
    remove_flows = self.matching_entries(match, priority, strict, out_port)
    self._remove_specific_entries(remove_flows, reason=reason)
    return remove_flows

  "Localiza a tabela de entrada de fluxo que corresponde ao pacote de dados ."
  "Retorna o maior tabela de entrada de fluxo de prioridade que corresponde ao pacote de dados"
  " na in_port dado, ou Nenhum se nenhuma entrada correspondente for encontrada ."
  def entry_for_packet (self, packet, in_port):
    """
    Finds the flow table entry that matches the given packet.

    Returns the highest priority flow table entry that matches the given packet
    on the given in_port, or None if no matching entry is found.
    """
    packet_match = ofp_match.from_packet(packet, in_port, spec_frags = True)

    for entry in self._table:
      if entry.match.matches_with_wildcards(packet_match,consider_other_wildcards=False):
        return entry
    return None

  "Testa se a entrada de entrada sobreponha a outra entrada nesta tabela ."

  "Retorna true se há uma sobreposição , caso contrário false . Uma vez que a tabela está"
  "classificados , existe apenas a necessidade de verificar uma certa porção do mesmo."
  "#NOTA : Assume que as entradas são classificadas segundo a diminuir effective_priority"
  "#NOTA : Ambíguo se a correspondência deve ser baseada em effective_priority"
  "# Ou a prioridade regular. Fazê-lo com base em effective_priority"
  "# Uma vez que é o que realmente afeta a correspondência de pacotes."
  "#NOTA : Poderíamos melhorar o desempenho , fazendo uma pesquisa binária para encontrar o"
  "# entradas direito de prioridade ."
  def check_for_overlapping_entry (self, in_entry):
    """
    Tests if the input entry overlaps with another entry in this table.

    Returns true if there is an overlap, false otherwise. Since the table is
    sorted, there is only a need to check a certain portion of it.
    """
    #NOTE: Assumes that entries are sorted by decreasing effective_priority
    #NOTE: Ambiguous whether matching should be based on effective_priority
    #      or the regular priority.  Doing it based on effective_priority
    #      since that's what actually affects packet matching.
    #NOTE: We could improve performance by doing a binary search to find the
    #      right priority entries.

    priority = in_entry.effective_priority

    for e in self._table:
      if e.effective_priority < priority:
        break
      elif e.effective_priority > priority:
        continue
      else:
        if e.is_matched_by(in_entry.match) or in_entry.is_matched_by(e.match):
          return True

    return False
