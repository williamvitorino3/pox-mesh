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

from pox.core import core
from pox.messenger.messenger import *

class MessengerExample (object):
  """
  Uma demonstração de mensageiro

  A ideia é muito simples. Quando você cria um MessengerExample,
  você diz a ele um nome que você está interessado dentro e
  ele escuta core.messenger! MessageReceived. Se ele vê uma mensagem
  com uma chave "Olá" onde o valor é o nome que você está interessado,
  ele reivindica a conexão que a mensagem veio em e, em seguida,
  escuta <thatConnection>! MessageReceived. Ele imprime mensagens sobre
  essa conexão a partir de então. Se uma mensagem tem uma chave chamada
  "bye" com o valor True, fecha a conexão.

  Para experimentá-lo, faça o seguinte no interpretador POX:
  POX> import pox.messenger.messenger_example
  POX> pox.messenger.messenger_example.MessengerExample ("foo")
  E então faça o seguinte a partir da linha de comando:
  Bash $ echo '{"hello": "foo"} [1,2,3] "limpo"' | Nc localhost 7790
  """
  """
  A demo of messenger.

  The idea is pretty simple. When you create a MessengerExample, you tell it a
  name you're interested in. It listens to core.messenger!MessageReceived. If
  it sees a message with a "hello" key where the value is the name you're
  interested in, it claims the connection that message came in on, and then
  listens to <thatConnection>!MessageReceived. It prints out messages on that
  connection from then on. If a message has a key named "bye" with the value
  True, it closes the connection

  To try it out, do the following in the POX interpreter:
  POX> import pox.messenger.messenger_example
  POX> pox.messenger.messenger_example.MessengerExample("foo")
  And then do the following from the commandline:
  bash$ echo '{"hello":"foo"}[1,2,3] "neat"' | nc localhost 7790
  """
  def __init__ (self, targetName):
    core.messenger.addListener(MessageReceived, self._handle_global_MessageReceived, weak=True)
    self._targetName = targetName

  def _handle_global_MessageReceived (self, event, msg):
    """
    Trata as mensagens globais recebidas.
    :param event: Evento que causa o lançamento do método.
    :param msg: Mensagem recebida.
    :return: Sem retorno.
    """
    try:
      n = msg['hello']
      if n == self._targetName:
        # It's for me!
        event.con.read() # Consume the message
        event.claim()
        event.con.addListener(MessageReceived, self._handle_MessageReceived, weak=True)
        print(self._targetName, "- started conversation with", event.con)
      else:
        print(self._targetName, "- ignoring", n)
    except:
      pass

  def _handle_MessageReceived (self, event, msg):
    """
    Trata as mensagens recebidas.
    :param event: Evento que causa o lançamento do método.
    :param msg: Mensagem recebida.
    :return: Sem retorno.
    """
    if event.con.isReadable():
      r = event.con.read()
      print(self._targetName, "-", r)
      if type(r) is dict and r.get("bye",False):
        print(self._targetName, "- GOODBYE!")
        event.con.close()
      if type(r) is dict and "echo" in r:
        event.con.send({"echo": r["echo"]})
    else:
      print(self._targetName, "- conversation finished")

examples = {}

def launch(name = "example"):
  """
  Adiciona valor no dicionário --examples
  :param name: Posição da informação no dicionário de exemplos.
  :return: Sem retorno.
  """
  examples[name] = MessengerExample(name)
