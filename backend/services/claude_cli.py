"""
Claude Code CLI transport — API key'siz Claude erişimi.

config/.env'de geçerli CLAUDE_API_KEY yoksa, bu makinede oturum açılmış
Claude Code CLI headless modda (`claude -p`) çağrılır. Kimlik doğrulama
CLI'ın kendi girişinden gelir (claude.ai hesabı / abonelik) — projeye
hiçbir anahtar yazılmaz.

Teknik notlar:
- Windows'ta `claude.cmd` shim'i cmd.exe üzerinden çalışır ve cmd.exe
  argüman içindeki %, ^, & ve satır sonlarını bozar. Bu yüzden shim yerine
  doğrudan `node cli.js` çağrılır (sistem promptu argüman olarak geçiyor).
- CLAUDECODE env değişkeni temizlenir — yoksa CLI iç içe oturum sanıp
  başlatmayı reddeder.
- Prompt stdin'den verilir (Windows komut satırı 32K karakter sınırı).
- --json-schema ile yapısal çıktı CLI tarafında doğrulanır (API'deki
  structured output'un karşılığı).
"""

import json
import os
import re
import shutil
import subprocess

import config

# CLI çağrı süreleri config.py'de (CLAUDE_CLI_*_TIMEOUT_SEC)
DEFAULT_TIMEOUT = config.CLAUDE_CLI_TIMEOUT_SEC

# Çocuk sürece CLAUDE*/ANTHROPIC_* değişkenlerinin HİÇBİRİ geçirilmez:
# - CLAUDECODE → iç içe oturum kilidi
# - CLAUDE_CODE_SSE_PORT / IDE entegrasyon değişkenleri → CLI bunlara
#   bağlanmaya çalışıp süresiz asılabilir (backend bir harness çocuğuyken)
# - ANTHROPIC_API_KEY/MODEL/BASE_URL → CLI kendi girişini kullanmalı
_SCRUB_PREFIXES = ("CLAUDE", "ANTHROPIC_")


def _clean_env() -> dict:
    return {
        k: v for k, v in os.environ.items()
        if not k.upper().startswith(_SCRUB_PREFIXES)
    }


class ClaudeCLIError(Exception):
    """CLI çağrısı başarısız oldu — mesaj kullanıcıya gösterilebilir."""


def _find_cli() -> list[str] | None:
    """
    Çalıştırılacak komutu döndürür.
    Tercih: [node.exe, cli.js] (shim'siz, cmd.exe bozulması yok).
    Geri dönüş: [claude.cmd] (yapı farklıysa).
    """
    override = config.CLAUDE_CLI_PATH
    candidates = []
    if override:
        candidates.append(override)
    which = shutil.which("claude")
    if which:
        candidates.append(which)

    for cand in candidates:
        base = os.path.dirname(cand)
        node = os.path.join(base, "node.exe")
        cli_js = os.path.join(base, "node_modules", "@anthropic-ai", "claude-code", "cli.js")
        if os.path.exists(node) and os.path.exists(cli_js):
            return [node, cli_js]

    if candidates:
        return [candidates[0]]
    return None


def parse_json_loose(text: str):
    """Model çıktısından JSON çıkarır: doğrudan, sonra kod bloğu/gövde içinden."""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


class ClaudeCLI:

    def __init__(self, model: str | None = None):
        self._cmd = _find_cli()
        self.model = model  # None → CLI'ın varsayılan modeli
        self.workdir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../data/cli_workspace")
        )
        os.makedirs(self.workdir, exist_ok=True)

    @property
    def available(self) -> bool:
        return self._cmd is not None

    def run(
        self,
        *,
        prompt: str,
        system_prompt: str | None = None,
        json_schema: dict | None = None,
        web_search: bool = False,
        effort: str = "high",
        model: str | None = None,
        resume: str | None = None,
        persist: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict:
        """
        Tek headless çağrı. Dönüş: CLI'ın JSON zarfı (result, session_id, …).
        persist=True → oturum diske kaydedilir, session_id ile --resume
        yapılarak sohbet bağlamı CLI tarafında sürdürülebilir.
        """
        if not self._cmd:
            raise ClaudeCLIError(
                "Claude Code CLI bulunamadı. 'claude' komutu PATH'te olmalı "
                "veya CLAUDE_CLI_PATH env değişkeniyle yolu belirtin."
            )

        cmd = list(self._cmd) + [
            "-p",
            "--output-format", "json",
            "--effort", effort,
        ]
        if not persist:
            cmd += ["--no-session-persistence"]
        if resume:
            cmd += ["--resume", resume]
        chosen_model = model or self.model
        if chosen_model:
            cmd += ["--model", chosen_model]
        if system_prompt:
            cmd += ["--system-prompt", system_prompt]
        if json_schema:
            cmd += ["--json-schema", json.dumps(json_schema, ensure_ascii=False)]
        if web_search:
            cmd += ["--tools", "WebSearch", "--allowedTools", "WebSearch"]
        else:
            cmd += ["--tools", ""]

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=self.workdir,
                env=_clean_env(),
            )
        except subprocess.TimeoutExpired:
            raise ClaudeCLIError(f"Claude CLI {timeout} saniyede yanıt vermedi (zaman aşımı).")

        envelope = parse_json_loose(proc.stdout)
        if envelope is None:
            detail = (proc.stderr or proc.stdout or "").strip()[:400]
            raise ClaudeCLIError(f"Claude CLI çıktısı çözümlenemedi: {detail}")

        if envelope.get("is_error"):
            raise ClaudeCLIError(self._friendly_error(envelope.get("result", "")))
        return envelope

    def complete(self, **kwargs) -> str:
        """run() kısayolu — yalnızca metin yanıtını döndürür."""
        return self.run(**kwargs).get("result", "")

    # ------------------------------------------------------------------
    # Kimlik yönetimi
    # ------------------------------------------------------------------

    def auth_status(self) -> dict:
        """
        `claude auth status` çıktısı: loggedIn, authMethod, email,
        subscriptionType… Hata durumunda {"loggedIn": False, "hata": ...}.
        """
        if not self._cmd:
            return {"loggedIn": False, "hata": "CLI bulunamadı"}
        try:
            proc = subprocess.run(
                list(self._cmd) + ["auth", "status"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=config.CLAUDE_CLI_STATUS_TIMEOUT_SEC, cwd=self.workdir, env=_clean_env(),
            )
            status = parse_json_loose(proc.stdout)
            if isinstance(status, dict):
                return status
            return {"loggedIn": False, "hata": (proc.stderr or proc.stdout or "").strip()[:200]}
        except Exception as e:
            return {"loggedIn": False, "hata": str(e)[:200]}

    def launch_login(self, email: str | None = None) -> bool:
        """
        Kullanıcının masaüstünde yeni bir konsolda `claude auth login`
        başlatır — tarayıcı açılır, kullanıcı abonelikli hesabıyla giriş
        yapar. email verilirse giriş sayfasında ön-doldurulur (doğru hesaba
        yönlendirme). Süreç beklenmez; durum auth_status() ile takip edilir.
        """
        if not self._cmd:
            raise ClaudeCLIError("Claude Code CLI bulunamadı — giriş başlatılamıyor.")
        cmd = list(self._cmd) + ["auth", "login"]
        if email and re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.\-]+", email):
            cmd += ["--email", email]
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(
            cmd,
            cwd=self.workdir,
            env=_clean_env(),
            creationflags=flags,
        )
        return True

    @staticmethod
    def _friendly_error(raw: str) -> str:
        low = (raw or "").lower()
        if "credit balance" in low:
            return (
                "Claude CLI hesabında kullanım hakkı yok ('credit balance is too low'). "
                "Bu makinedeki CLI girişi abonelikli hesaba bağlı değil. Çözüm: terminalde "
                "'claude' çalıştırıp /login ile Claude aboneliği olan hesaba giriş yapın "
                "(veya config/.env'e bir CLAUDE_API_KEY ekleyin)."
            )
        if "log in" in low or "login" in low or "authentication" in low:
            return (
                "Claude CLI oturumu yok ya da süresi dolmuş. Terminalde 'claude' çalıştırıp "
                "/login ile giriş yapın."
            )
        return f"Claude CLI hatası: {(raw or 'bilinmeyen hata')[:300]}"
