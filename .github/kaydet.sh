#!/usr/bin/env bash
# durum/ klasöründeki değişiklikleri depoya yazar. İki iş aynı anda çalışırsa birkaç kez yeniden dener.
set -euo pipefail
git config user.name "deprem-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add durum/
if git diff --cached --quiet; then
  echo "Durum değişmedi."
  exit 0
fi
git commit -q -m "Durum: $1"
for attempt in 1 2 3 4 5; do
  if git pull -q --rebase && git push -q; then
    echo "Durum kaydedildi."
    exit 0
  fi
  sleep $(( attempt * 3 ))
done
echo "Durum kaydedilemedi." >&2
exit 1
