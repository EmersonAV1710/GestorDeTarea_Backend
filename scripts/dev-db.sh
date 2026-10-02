#!/usr/bin/env bash
set -euo pipefail

pgdata="${HOME}/proyectos/.gestor-tareas-pg/data"
pglog="${HOME}/proyectos/.gestor-tareas-pg/postgresql.log"
pgctl="$(pg_config --bindir)/pg_ctl"
action="${1:-status}"

if [[ ! -d "$pgdata" ]]; then
  echo "No existe el clúster local: $pgdata" >&2
  echo "Consulta README.md para preparar PostgreSQL en una instalación nueva." >&2
  exit 1
fi

case "$action" in
  start)
    "$pgctl" -D "$pgdata" -l "$pglog" \
      -o "-c listen_addresses=localhost -c port=5434 -c unix_socket_directories=/tmp" start
    ;;
  stop)
    "$pgctl" -D "$pgdata" stop -m fast
    ;;
  status)
    "$pgctl" -D "$pgdata" status
    ;;
  *)
    echo "Uso: $0 {start|stop|status}" >&2
    exit 2
    ;;
esac
