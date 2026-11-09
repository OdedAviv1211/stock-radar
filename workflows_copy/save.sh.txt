#!/usr/bin/env bash
# שמירה עמידה להתנגשויות: commit של הקבצים שצוינו, ואז fetch + rebase + push – עד 5 ניסיונות.
# שימוש:  bash .github/scripts/save.sh "<הודעת commit>" <קבצים...>
# אם ה-rebase נכשל (שני תהליכים שינו את אותו קובץ): כשמוגדר RERUN – חוזרים ל-main העדכני, מריצים שוב את
# הפקודה שב-RERUN (החישוב חוזר על הנתונים העדכניים) ומתחייבים מחדש; אחרת שומרים את הגרסה של הריצה הזו.
set -u
msg="$1"; shift
branch="${GITHUB_REF_NAME:-main}"
git config user.name "stock-radar-bot"
git config user.email "actions@users.noreply.github.com"
for i in 1 2 3 4 5; do
  git add -- "$@" 2>/dev/null || true
  git commit -qm "$msg" >/dev/null 2>&1 || true
  git fetch -q origin "$branch"
  if [ -z "$(git log --oneline "origin/$branch..HEAD" 2>/dev/null)" ]; then
    echo "nothing to push"; exit 0
  fi
  if git rebase -q "origin/$branch"; then
    if git push -q origin "HEAD:$branch"; then echo "pushed (attempt $i)"; exit 0; fi
    echo "push rejected – retrying"
  else
    echo "rebase conflict (attempt $i)"
    if [ -n "${RERUN:-}" ]; then
      git rebase --abort 2>/dev/null || true
      git reset -q --hard "origin/$branch"
      echo "re-running on the fresh branch: $RERUN"
      bash -c "$RERUN" || echo "rerun failed – saving whatever was produced"
    else
      # שומרים את הגרסה של הריצה הזו (ב-rebase היא "theirs") לקבצים שהתנגשו וממשיכים
      git checkout --theirs -- . 2>/dev/null || true
      git add -A
      GIT_EDITOR=true git rebase --continue || { git rebase --abort 2>/dev/null || true; git reset -q --hard "origin/$branch"; }
    fi
  fi
  sleep $((i * 15))
done
echo "::error::could not push after 5 attempts"; exit 1
