#!/bin/bash
# Çift tıklayınca Deprem X panelini açar. Kapatmak için bu Terminal penceresini kapatın.
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
python3 panel.py
