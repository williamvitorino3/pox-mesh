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
Lets you start a default instance of the datapath, for what it's worth.
--------------------------------------------------------------------------
Permite iniciar uma instância padrão do caminho de dados, pelo que vale a pena.

Example:
./pox.py --no-openflow datapaths:softwareswitch --address=localhost
"""

from pox.lib.ioworker.workers import BackoffWorker
from pox.datapaths.switch import SoftwareSwitch, OFConnection
from pox.datapaths.switch import ExpireMixin
from pox.lib.util import dpid_to_str, str_to_dpid


class OpenFlowWorker (BackoffWorker):
  #"Classe Trabalhador OpenFlow"
  #"Saída do Trabalhador"
  def __init__ (self, switch=None, **kw):
    self.switch = switch
    self.connection = None
    from pox.core import core
    self.log = core.getLogger("dp." + dpid_to_str(self.switch.dpid))
    super(OpenFlowWorker, self).__init__(switch=switch,**kw)
    self._info("Connecting to %s:%s", kw.get('addr'), kw.get('port'))

   
  def _handle_close (self):
    #"Fechar o controle"
    super(OpenFlowWorker, self)._handle_close()

   
  def _handle_connect (self):
    #"Conectar o controle"
    super(OpenFlowWorker, self)._handle_connect()
    self.connection = OFConnection(self)
    self.switch.set_connection(self.connection)
    self._info("Connected to controller")

   
  def _error (self, *args, **kw):
    #"Define caso de erro"
    self.log.error(*args,**kw)
   
  def _warn (self, *args, **kw):
    #"Define avisos "
    self.log.warn(*args,**kw)
   
  def _info (self, *args, **kw):
    #"Define informaçoes"
    self.log.info(*args,**kw)
   
  def _debug (self, *args, **kw):
    #"Define  o debug - depuração"
    self.log.debug(*args,**kw)

def do_launch (cls, address = '127.0.0.1', port = 6633, max_retry_delay = 16,
    dpid = None, extra_args = None, **kw):
  #"Fazer o lançamento"
  """
  Used for implementing custom switch launching functions

  cls is the class of the switch you want to add.

  Returns switch instance.

 ------------------------------------
 Usado para implementar funções de inicialização de chaves personalizadas

   Cls é a classe do switch que você deseja adicionar.

   Retorna a instância do switch.
  """
  
  if extra_args is not None:
    #"Se extra_args não é vazio, importa ast, modifica extra_args e o atualiza"
    import ast
    extra_args = ast.literal_eval('{%s}' % (extra_args,))
    kw.update(extra_args)

   
  from pox.core import core
  #"importa core; se core não tem o componente datapaths,"
  #"registra esse componente e faz o _switches receber core.datapaths"
  if not core.hasComponent('datapaths'):
    core.register("datapaths", {})
  _switches = core.datapaths

  #"se dpid é vazio, inicia um laço dpid de 1 a 256"
  #"se dpid não está em _switches, para a execução"
  #"se dpid está, constroe um RuntimeError coma  mensagem: Fora de DPIDs"
  #"se dpid é vazio, o faz receber str_to_dpid(dpid)"
  if dpid is None:
    for dpid in range(1,256):
      if dpid not in _switches: break
    if dpid in _switches:
      raise RuntimeError("Out of DPIDs")
  else:
    dpid = str_to_dpid(dpid)

  switch = cls(dpid=dpid, name="sw"+str(dpid), **kw)
  _switches[dpid] = switch

  port = int(port)
  max_retry_delay = int(max_retry_delay)

  
  def up (event):
    #"Aumentar"
    import pox.lib.ioworker
    global loop
    loop = pox.lib.ioworker.RecocoIOLoop()
    #loop.more_debugging = True
    loop.start()
    OpenFlowWorker.begin(loop=loop, addr=address, port=port,
        max_retry_delay=max_retry_delay, switch=switch)

  from pox.core import core

  core.addListenerByName("UpEvent", up)

  return switch


def softwareswitch (address='127.0.0.1', port = 6633, max_retry_delay = 16,
    dpid = None, extra = None, __INSTANCE__ = None):
  #"Define software do switch com endereço, porta, maximo de repeticao, dpid, extra"
  """
  Launches a SoftwareSwitch

  Not particularly useful, since SoftwareSwitch doesn't do much.
 --------------------------------------------------------------
 Não é particularmente útil, já que o SoftwareSwitch não faz muito.
  """
  from pox.core import core
  
  core.register("datapaths", {})
  #"Registra o datapaths no core"
  
  class ExpiringSwitch(ExpireMixin, SoftwareSwitch):
    #"Classe para expiração do switch"
    pass
  
  do_launch(ExpiringSwitch, address, port, max_retry_delay, dpid,
            extra_args = extra)
    #"Fazer o lançamento com ExpiringSwitch, endereço, porta, maximo de repeticao, dpid e extra"