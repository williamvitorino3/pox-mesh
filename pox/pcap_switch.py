# -*- coding: utf-8 -*-
# Copyright 2013 James McCauley
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
Software switch with PCap ports
Comutador de software com portas PCap

Example:
./pox.py --no-openflow datapaths.pcap_switch --address=localhost
"""

from pox.core import core
from pox.datapaths import do_launch
from pox.datapaths.switch import SoftwareSwitchBase, OFConnection
from pox.datapaths.switch import ExpireMixin
import pox.lib.pxpcap as pxpcap
from Queue import Queue
from threading import Thread
import pox.openflow.libopenflow_01 as of
from pox.lib.packet import ethernet
import logging

log = core.getLogger()

DEFAULT_CTL_PORT = 7791

_switches = {}


def _do_ctl (event):
  #"se r é null, r recebe Okay"
  r = _do_ctl2(event)
  if r is None:
    r = "Okay."
  event.worker.send(r + "\n")


def _do_ctl2 (event):
  #"define o ctl2, constroe um RuntimeError com a mensagem e argumentos"
  def errf (msg, *args):
    raise RuntimeError(msg % args)

  args = event.args

  
  def ra (low, high = None):
    #"se altura(high) é null, recebe baixo(low)"
    #"se o tamanho dos args é menor que high ou tamanho dos args é maior que high"
    #"constroe uma mensagem de erro: Numero errado de argumentos"
    if high is None: high = low
    if len(args) < low or len(args) > high:
      raise RuntimeError("Wrong number of arguments")
    return False

  #"verifica se o primeiro evento é: add-port, del-port ou show"
  #"se não for nenhum, constroe a mensagem de erro: Comando desconhecido durante o processamento do comando"
  try:
    if event.first == "add-port":
      ra(1,2)
      if len(event.args) == 1 and len(_switches) == 1:
        sw = _switches[_switches.keys()[0]]
        p = args[0]
      else:
        ra(2)
        if event.args[0] not in _switches:
          raise RuntimeError("No such switch")
        sw = _switches[event.args[0]]
        p = args[1]
      sw.add_interface(p, start=True, on_error=errf)
    elif event.first == "del-port":
      ra(1,2)
      if len(event.args) == 1:
        for sw in _switches.values():
          for p in sw.ports:
            if p.name == event.args[0]:
              sw.remove_interface(event.args[0])
              return
        raise RuntimeError("No such interface")
      sw = _switches[event.args[0]]
      sw.remove_interface(args[1])
    elif event.first == "show":
      ra(0)
      s = []
      for sw in _switches.values():
        s.append("Switch %s" % (sw.name,))
        for no,p in sw.ports.iteritems():
          s.append(" %3s %s" % (no, p.name))
      return "\n".join(s)

    else:
      raise RuntimeError("Unknown command")

  except Exception as e:
    log.exception("While processing command")
    return "Error: " + str(e)


def launch (address = '127.0.0.1', port = 6633, max_retry_delay = 16,
    dpid = None, ports = '', extra = None, ctl_port = None,
    __INSTANCE__ = None):
  #"Define o lançamento"
  """
  Launches a switch
  Lança um interruptor
  """

  
  if not pxpcap.enabled:
    raise RuntimeError("You need PXPCap to use this component")
    #"Se não é pxpcap.enabled, constroe a mensagem de erro: você necessita de PXPCap para usar este componente"

  
  if ctl_port:
    if core.hasComponent('ctld'):
      raise RuntimeError("Only one ctl_port is allowed")
      #"Se é ctl_port, Somente uma ctl_port é permitido"

    
    if ctl_port is True:
      ctl_port = DEFAULT_CTL_PORT
      #"Se ctl_port é True, ctl_port recebe DEFAULT_CTL_PORT"

    import ctl
    ctl.server(ctl_port)
    core.ctld.addListenerByName("CommandEvent", _do_ctl)

  _ports = ports.strip()

  
  def up (event):
    #"Define up"
    ports = [p for p in _ports.split(",") if p]

    sw = do_launch(PCapSwitch, address, port, max_retry_delay, dpid,
                   ports=ports, extra_args=extra)
    _switches[sw.name] = sw

  core.addListenerByName("UpEvent", up)


class PCapSwitch (ExpireMixin, SoftwareSwitchBase):
  #"Classe PCapSwitch"
  # Default level for loggers of this class
  # Nível predefinido para registadores desta classe
  default_log_level = logging.INFO

  def __init__ (self, **kw):
    """
    Create a switch instance

    Additional options over superclass:
    log_level (default to default_log_level) is level for this instance
    ports is a list of interface names
    -------------------------------------------------------------------
    Criar uma instância de switch

     Opções adicionais sobre a superclasse:
     Log_level (padrão para default_log_level) é level para esta instância
     Ports é uma lista de nomes de interface
    """
    log_level = kw.pop('log_level', self.default_log_level)

    self.q = Queue()
    self.t = Thread(target=self._consumer_threadproc)
    core.addListeners(self)

    ports = kw.pop('ports', [])
    kw['ports'] = []

    super(PCapSwitch,self).__init__(**kw)

    self._next_port = 1

    self.px = {}

    for p in ports:
      self.add_interface(p, start=False)

    self.log.setLevel(log_level)

    for px in self.px.itervalues():
      px.start()

    self.t.start()

  
  def add_interface (self, name, port_no=-1, on_error=None, start=False):
    #"Adicionar interface"
    if on_error is None:
      on_error = log.error

    devs = pxpcap.PCap.get_devices()
    if name not in devs:
      on_error("Device %s not available -- ignoring", name) #Serviço x não disponível - ignorado
      return
    dev = devs[name]
    if dev.get('addrs',{}).get('ethernet',{}).get('addr') is None:
      on_error("Device %s has no ethernet address -- ignoring", name) #Serviço x não tem endereço ethernet
      return
    if dev.get('addrs',{}).get('AF_INET') != None:
      on_error("Device %s has an IP address -- ignoring", name) #Serviço x tem um endereço IP  - ignorado
      return
    for no,p in self.px.iteritems():
      if p.device == name:
        on_error("Device %s already added", name) #Serviço x já foi adicionado

    if port_no == -1:
      while True:
        port_no = self._next_port
        self._next_port += 1
        if port_no not in self.ports: break

    if port_no in self.ports:
      on_error("Port %s already exists -- ignoring", port_no) #Porta x já existe - ignorado
      return

    phy = of.ofp_phy_port()
    phy.port_no = port_no
    phy.hw_addr = dev['addrs']['ethernet']['addr']
    phy.name = name
    # Fill in features sort of arbitrarily
    # Preencha recursos de forma arbitrária
    phy.curr = of.OFPPF_10MB_HD #OFPPF_10MB_HD: Suporte de taxa half-duplex de 10 Mb
    phy.advertised = of.OFPPF_10MB_HD 
    phy.supported = of.OFPPF_10MB_HD
    phy.peer = of.OFPPF_10MB_HD

    self.add_port(phy)

    px = pxpcap.PCap(name, callback = self._pcap_rx, start = False)
    px.port_no = phy.port_no
    self.px[phy.port_no] = px

    if start:
      px.start()

    return px

  
  def remove_interface (self, name_or_num):
    #"Remover interface"
    if isinstance(name_or_num, basestring):
      for no,p in self.px.iteritems():
        if p.device == name_or_num:
          self.remove_interface(no)
          return
      raise ValueError("No such interface") # Nenhuma dessas interfaces

    px = self.px[name_or_num]
    px.stop()
    px.port_no = None
    self.delete_port(name_or_num)

  
  def _handle_GoingDownEvent (self, event):
    #"Manipular o evento 'indo para baixo'"
    self.q.put(None)

  
  def _consumer_threadproc (self):
    #"Define o _consumer_threadproc"
    timeout = 3
    while core.running:
      try:
        data = self.q.get(timeout=timeout)
      except:
        continue
      if data is None:
        # Signal to quit
        # Sinal para sair
        break
      batch = []
      while True:
        self.q.task_done()
        port_no,data = data
        data = ethernet(data)
        batch.append((data,port_no))
        try:
          data = self.q.get(block=False)
        except:
          break
      core.callLater(self.rx_batch, batch)

  
  def rx_batch (self, batch):
    #"Define o rx_batch"
    for data,port_no in batch:
      self.rx_packet(data, port_no)

  
  def _pcap_rx (self, px, data, sec, usec, length):
    #"Define o rx pcap"
    if px.port_no is None: return
    self.q.put((px.port_no, data))

  
  def _output_packet_physical (self, packet, port_no):
    #"Define a saída do pacote físico"
    """
    send a packet out a single physical port

    This is called by the more general _output_packet().
    ----------------------------------------------------
    Enviar um pacote para fora uma única porta física

     Isso é chamado pelo mais geral _output_packet ().
    """
    px = self.px.get(port_no)
    if not px: return
    px.inject(packet)
