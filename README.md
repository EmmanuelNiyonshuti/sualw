# sualw
A small CLI tool that silences a process, gives you back your terminal, and lets you view the logs later on demand.


## Installation:
If you are interested, since it hasn’t been published on PyPI yet, you can install it like this:
```bash
pip install git+https://github.com/EmmanuelNiyonshuti/sualw.git
```

Try it out:
```bash
$ sualw uvicorn main:app --reload

Ok.  uvicorn is running quietly  (pid 11292)
   log     ->  /home/emmanuel/.sualw/logs/uvicorn.log
   watch   ->  sualw toggle uvicorn
   stop    ->  sualw stop uvicorn
$ 
```

List all running processes with:
```bash
$ sualw list

 NAME      PID     STATUS    UPTIME   COMMAND                                      
───────────────────────────────────────────────────────────────────────────────────
 uvicorn   11292   running   -7035s   /home/emmanuel/works/sualw/.venv/bin/uvicorn 
                                      main:app --reload
$
```
Get back the logs with:

```bash
$ sualw toggle uvicorn

⟳  uvicorn  (live) - Ctrl+C to detach

WARNING:  StatReload detected changes in 'main.py'. Reloading...
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO:     Application shutdown complete.
INFO:     Finished server process [11296]
INFO:     Started server process [12417]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

stop the process with:
```bash
$ sualw stop uvicorn

✓  uvicorn received SIGTERM.

```
It was built out of my need to suppress webserver logs during development and get them back when I need them.There are other tools that can do similar things, but they felt a bit overkill for my simple use case, or maybe I just didn’t explore them well enough.

`sualw` will save these logs in the home directory under `~/.sualw/logs/{process_name}.log` file, keep a json file registry for all processes in `~/.sualw/registry.json`.

you can name the process anything you want, it must come before the `--` separator right after `sualw` command, It will not be the name you name your process for example if you run some process that accepts a name and you pass it afterwars `sualw myprocess --myprocess_name` it will not be named `myprocess_name` but `myprocess`.

