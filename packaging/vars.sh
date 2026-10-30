#!/usr/bin/env bash
# Ortak paketleme değişkenleri — CI ve yerel derlemede aynı şekilde çalışır.
# Ortam değişkeni verilerek değerler geçersiz kılınabilir (örn. VERSION=1.0.1).

export APP_ID="${APP_ID:-idm-linux}"
export DISPLAY_NAME="${DISPLAY_NAME:-IDM LINUX}"
export VERSION="${VERSION:-1.0.0}"
export VENDOR="${VENDOR:-BELGESELSEMO}"
export MAINTAINER="${MAINTAINER:-BELGESELSEMO <belgeselsemo@users.noreply.github.com>}"
export HOMEPAGE="${HOMEPAGE:-https://github.com/BELGESELSEMO/IDM-LINUX}"
