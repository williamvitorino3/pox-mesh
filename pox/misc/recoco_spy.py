# Copyright 2012 James McCauley
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
This is an extremely primitive start at some debugging.
At the moment, it is really just for recoco (maybe it belongs in there?).
"""
"""
Este é um começo extremamente primitivo em alguma depuração.
No momento, é realmente apenas para rococo (talvez ele pertence lá?).
"""

from pox.core import core
log = core.getLogger()
import time
import traceback
import pox.lib.recoco

_frames = []

def _tf (frame, event, arg):
  """
  Gerência a lista de quadros.
  :param frame: Quadro Ethernet.
  :param event: Evento relacionado à chamada da função.
  :param arg: Argumentos do quadro.
  :return: Refencia da própria função.
  """
  if _frames is None: return _tf
  #print " " * len(_frames) + event
  if event == 'call':
    _frames.append(frame)
    return _tf
  elif event == 'line':
    return _tf
  elif event == 'exception':
    #_frames.pop()
    return _tf
  elif event == 'return':
    _frames.pop()
  elif event == 'c_call':
    print "c_call"
    _frames.append((frame,arg))
  elif event == 'c_exception':
    _frames.pop()
  elif event == 'c_return':
    _frames.pop()


def _trace_thread_proc ():
  """
  Percorre todos os quadros da lista à procura de alguma irregularidade.
  :return: Sem retorno.
  """
  last = None
  last_time = None
  warned = None
  while True:
    try:
      time.sleep(1)
      c = len(_frames)
      if c == 0: continue
      f = _frames[-1]
      stopAt = None
      count = 0
      sf = f
      # Roda todos os quadros.
      while sf is not None: # Enquanto o quadro não estiver vazio.
        if sf.f_code == pox.lib.recoco.Scheduler.cycle.im_func.func_code:   # Verifica se as funções são iguais.
          stopAt = sf # Identifica o quadro de parada.
          break # Sai do laço.
        # Se não.
        count += 1  # Incrementa o contador.
        sf = sf.f_back  # Pega o próximo quadro.
      #if stopAt == None: continue

      f = "\n".join([s.strip() for s in
                      traceback.format_stack(f,count)])
      #f = " / ".join([s.strip() for s in
      #                traceback.format_stack(f,1)[0].strip().split("\n")])
      #f = "\n".join([s.strip() for s in
      #                traceback.format_stack(f)])

      if f != last:   # Se f não for o último.
        if warned:  # Se já avisou...
          log.warning("Running again")  # Lança o aviso.
        warned = None   # Restalra o valor da variável.
        last = f  # f se torna o último quadro.
        last_time = time.time() # Pega o tempo que passou.
      elif f != warned:   # Se não tiver avisado.
        if time.time() - last_time > 3: # Se o tempo percorrido - o tempo final for maior que 3.
          if stopAt is not None:  # Se a padara não for None.
            warned = f    # avisado recebe o quadro f
            log.warning("Stuck at:\n" + f)  # Lança o aviso para o usuário.

      #from pox.core import core
      #core.f = f

    except: # Caso ocorra qualquer erro.
      traceback.print_exc() # Mostra o erro.
      pass



def launch ():
  """
  Lança nova thread de _trace_thread_proc.
  :return: Sem retorno.
  """
  def f ():
    import sys
    sys.settrace(_tf)
  core.callLater(f)

  import threading
  _trace_thread = threading.Thread(target=_trace_thread_proc)
  _trace_thread.daemon = True
  _trace_thread.start()
