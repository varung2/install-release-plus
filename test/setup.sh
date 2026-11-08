#!/bin/bash
# set -x
cd "$(dirname "$0")/.."

function ensure_host_config_file {
  local host_config="$HOME/.config/install_release/config.json"
  mkdir -p "$(dirname "$host_config")"
  if [ ! -f "$host_config" ]; then
    echo '{"config": {}}' >"$host_config"
  fi
}

function build_ubuntu {
  docker build -t install-release-plus-ubuntu:latest -f test/images/ubuntu/Dockerfile .
}

function build_fedora {
  docker build -t install-release-plus-fedora:latest -f test/images/fedora/Dockerfile .
}

case $1 in
  "ubuntu")
    ensure_host_config_file
    docker rm -f irp-ubuntu
    docker images | grep install-release-plus-ubuntu || build_ubuntu
    docker run -d \
      --name irp-ubuntu \
      -v "$(pwd)/InstallRelease":/app/InstallRelease \
      -v "$HOME/.config/install_release/config.json":/root/.config/install_release/config.json:ro \
      -v "$(pwd)/cli":/app/cli \
      -v "$(pwd)/pyproject.toml":/app/pyproject.toml \
      -v "$(pwd)/uv.lock":/app/uv.lock \
      -v u-irp:/app/.venv \
      -e HOME=/root \
      install-release-plus-ubuntu:latest
    docker exec irp-ubuntu bash -c '/usr/local/bin/uv sync --dev'
    # docker exec -it irp-ubuntu bash
    ;;
  "fedora")
    ensure_host_config_file
    docker rm -f irp-fedora
    docker images | grep install-release-plus-fedora || build_fedora
    docker run -d \
      --name irp-fedora \
      -v "$(pwd)/InstallRelease":/app/InstallRelease \
      -v "$HOME/.config/install_release/config.json":/root/.config/install_release/config.json:ro \
      -v "$(pwd)/cli":/app/cli \
      -v "$(pwd)/pyproject.toml":/app/pyproject.toml \
      -v "$(pwd)/uv.lock":/app/uv.lock \
      -v f-irp:/app/.venv \
      -e HOME=/root \
      install-release-plus-fedora:latest
    docker exec irp-fedora bash -c '/usr/local/bin/uv sync --dev'
    docker exec -it irp-fedora bash

    ;;
  "build")
    build_ubuntu
    build_fedora
    ;;
  *)
    echo "Usage: $0 [ubuntu|fedora]"
    exit 1
    ;;
esac
