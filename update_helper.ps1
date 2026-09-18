param(
    [Parameter(Mandatory = $true)]
    [int]$ParentPid,
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [string]$StagingDir = "",
    [string]$BackupDir = "",
    [string]$InstallerPath = "",
    [Parameter(Mandatory = $true)]
    [string]$ExeName,
    [string]$RestartArgs = "",
    [string]$ReadyFile = "",
    [string]$Language = "en",
    # Tests only: prove the script starts and reads its arguments, then stop.
    [switch]$SelfTest
)

Set-Location $env:TEMP
$logPath = Join-Path $env:TEMP "AccessibleIPTVClient_update.log"
# Why the update failed, for the app to report when it starts again. The step
# log alone only ever reached the user as a path they had to go and open, so
# a failure could be reported six times over without anyone learning its cause
# (issue #26). updater.read_update_result reads this file.
$resultPath = Join-Path $env:TEMP "AccessibleIPTVClient_update_result.json"

function Write-Log {
    param([string]$Message)
    try {
        $stamp = (Get-Date).ToString("o")
        Add-Content -Path $logPath -Value "$stamp $Message"
    } catch { }
}

# Logged before anything that can fail, so an update that stops early still
# leaves a line saying the helper ran at all (issue #26 left no trace).
Write-Log "Update helper started (PID $PID, PowerShell $($PSVersionTable.PSVersion)). InstallDir=$InstallDir InstallerPath=$InstallerPath StagingDir=$StagingDir"

if ($SelfTest) {
    if ($ReadyFile) { New-Item -ItemType File -Path $ReadyFile -Force | Out-Null }
    exit 0
}

try { Remove-Item -LiteralPath $resultPath -Force -ErrorAction SilentlyContinue } catch { }

trap {
    Write-Log "Unhandled error: $($_.Exception.Message) at line $($_.InvocationInfo.ScriptLineNumber)"
    continue
}

# Windows PowerShell 5.1 reads a BOM-less script through the machine's legacy
# ANSI code page. Keep this file ASCII and encode translated text as JSON
# Unicode escapes; ConvertFrom-Json restores real Unicode strings for WinForms
# and screen readers. The helper cannot use the Python gettext catalogue while
# the application directory is being replaced, so it carries this small,
# self-contained set and falls back to English for an unknown language.
$UpdateMessagesJson = @'
{
  "en": {
    "prepare": "Preparing the update. The application is closing; installation will start as soon as it closes.",
    "consent": "Windows will now ask for permission to install the update. Please allow it.",
    "install": "Installing the update. This can take a minute; please leave this window open.",
    "start": "Starting the updated application...",
    "error": "The update did not finish. Please try again from the Help menu in the application."
  },
  "es": {
    "prepare": "Preparando la actualizaci\u00f3n. La aplicaci\u00f3n se est\u00e1 cerrando; la instalaci\u00f3n comenzar\u00e1 en cuanto se cierre.",
    "consent": "Windows pedir\u00e1 ahora permiso para instalar la actualizaci\u00f3n. Perm\u00edtalo, por favor.",
    "install": "Instalando la actualizaci\u00f3n. Esto puede tardar un minuto; deje esta ventana abierta.",
    "start": "Iniciando la versi\u00f3n actualizada de la aplicaci\u00f3n...",
    "error": "La actualizaci\u00f3n no termin\u00f3. Int\u00e9ntelo de nuevo desde el men\u00fa Ayuda de la aplicaci\u00f3n."
  },
  "ar": {
    "prepare": "\u062c\u0627\u0631\u064d \u062a\u062d\u0636\u064a\u0631 \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u064a\u062a\u0645 \u0625\u063a\u0644\u0627\u0642 \u0627\u0644\u062a\u0637\u0628\u064a\u0642\u061b \u0633\u064a\u0628\u062f\u0623 \u0627\u0644\u062a\u062b\u0628\u064a\u062a \u0628\u0645\u062c\u0631\u062f \u0625\u063a\u0644\u0627\u0642\u0647.",
    "consent": "\u0633\u064a\u0637\u0644\u0628 Windows \u0627\u0644\u0622\u0646 \u0627\u0644\u0625\u0630\u0646 \u0628\u062a\u062b\u0628\u064a\u062a \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u064a\u064f\u0631\u062c\u0649 \u0627\u0644\u0633\u0645\u0627\u062d \u0628\u0630\u0644\u0643.",
    "install": "\u062c\u0627\u0631\u064d \u062a\u062b\u0628\u064a\u062a \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u0642\u062f \u064a\u0633\u062a\u063a\u0631\u0642 \u0630\u0644\u0643 \u062f\u0642\u064a\u0642\u0629\u061b \u064a\u064f\u0631\u062c\u0649 \u062a\u0631\u0643 \u0647\u0630\u0647 \u0627\u0644\u0646\u0627\u0641\u0630\u0629 \u0645\u0641\u062a\u0648\u062d\u0629.",
    "start": "\u062c\u0627\u0631\u064d \u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u0625\u0635\u062f\u0627\u0631 \u0627\u0644\u0645\u062d\u062f\u0651\u062b \u0645\u0646 \u0627\u0644\u062a\u0637\u0628\u064a\u0642...",
    "error": "\u0644\u0645 \u064a\u0643\u062a\u0645\u0644 \u0627\u0644\u062a\u062d\u062f\u064a\u062b. \u064a\u064f\u0631\u062c\u0649 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 \u0645\u0631\u0629 \u0623\u062e\u0631\u0649 \u0645\u0646 \u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u0645\u0633\u0627\u0639\u062f\u0629 \u0641\u064a \u0627\u0644\u062a\u0637\u0628\u064a\u0642."
  },
  "pt": {
    "prepare": "Preparando a atualiza\u00e7\u00e3o. O aplicativo est\u00e1 sendo fechado; a instala\u00e7\u00e3o come\u00e7ar\u00e1 assim que ele for fechado.",
    "consent": "O Windows vai pedir permiss\u00e3o para instalar a atualiza\u00e7\u00e3o. Por favor, permita.",
    "install": "Instalando a atualiza\u00e7\u00e3o. Isso pode levar um minuto; deixe esta janela aberta.",
    "start": "Iniciando o aplicativo atualizado...",
    "error": "A atualiza\u00e7\u00e3o n\u00e3o foi conclu\u00edda. Tente novamente pelo menu Ajuda do aplicativo."
  },
  "fr": {
    "prepare": "Pr\u00e9paration de la mise \u00e0 jour. L\u2019application est en cours de fermeture ; l\u2019installation commencera d\u00e8s qu\u2019elle sera ferm\u00e9e.",
    "consent": "Windows va maintenant demander l\u2019autorisation d\u2019installer la mise \u00e0 jour. Veuillez l\u2019accepter.",
    "install": "Installation de la mise \u00e0 jour. Cela peut prendre une minute ; veuillez laisser cette fen\u00eatre ouverte.",
    "start": "D\u00e9marrage de la version mise \u00e0 jour de l\u2019application...",
    "error": "La mise \u00e0 jour ne s\u2019est pas termin\u00e9e. R\u00e9essayez depuis le menu Aide de l\u2019application."
  },
  "de": {
    "prepare": "Das Update wird vorbereitet. Die Anwendung wird beendet; die Installation beginnt, sobald das Programm geschlossen ist.",
    "consent": "Windows fragt jetzt nach der Berechtigung, das Update zu installieren. Bitte erlauben Sie es.",
    "install": "Das Update wird installiert. Dies kann eine Minute dauern; bitte lassen Sie dieses Fenster ge\u00f6ffnet.",
    "start": "Die aktualisierte Anwendung wird gestartet...",
    "error": "Das Update wurde nicht abgeschlossen. Bitte versuchen Sie es \u00fcber das Hilfe-Men\u00fc der Anwendung erneut."
  },
  "ru": {
    "prepare": "\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f. \u041f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435 \u0437\u0430\u043a\u0440\u044b\u0432\u0430\u0435\u0442\u0441\u044f; \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 \u043d\u0430\u0447\u043d\u0451\u0442\u0441\u044f \u0441\u0440\u0430\u0437\u0443 \u043f\u043e\u0441\u043b\u0435 \u0437\u0430\u043a\u0440\u044b\u0442\u0438\u044f.",
    "consent": "\u0421\u0435\u0439\u0447\u0430\u0441 Windows \u0437\u0430\u043f\u0440\u043e\u0441\u0438\u0442 \u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u0438\u0435 \u043d\u0430 \u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0443 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f. \u041f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430, \u0440\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u0435 \u0435\u0451.",
    "install": "\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f. \u042d\u0442\u043e \u043c\u043e\u0436\u0435\u0442 \u0437\u0430\u043d\u044f\u0442\u044c \u043c\u0438\u043d\u0443\u0442\u0443; \u043e\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u044d\u0442\u043e \u043e\u043a\u043d\u043e \u043e\u0442\u043a\u0440\u044b\u0442\u044b\u043c.",
    "start": "\u0417\u0430\u043f\u0443\u0441\u043a \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d\u043d\u043e\u0439 \u0432\u0435\u0440\u0441\u0438\u0438 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f...",
    "error": "\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435 \u043d\u0435 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u043e. \u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u043f\u043e\u043f\u044b\u0442\u043a\u0443 \u0447\u0435\u0440\u0435\u0437 \u043c\u0435\u043d\u044e \u00ab\u0421\u043f\u0440\u0430\u0432\u043a\u0430\u00bb \u0432 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0438."
  },
  "tr": {
    "prepare": "G\u00fcncelleme haz\u0131rlan\u0131yor. Uygulama kapan\u0131yor; kapand\u0131\u011f\u0131nda kurulum ba\u015flayacak.",
    "consent": "Windows \u015fimdi g\u00fcncellemeyi y\u00fcklemek i\u00e7in izin isteyecek. L\u00fctfen izin verin.",
    "install": "G\u00fcncelleme y\u00fckleniyor. Bu i\u015flem bir dakika s\u00fcrebilir; l\u00fctfen bu pencereyi a\u00e7\u0131k b\u0131rak\u0131n.",
    "start": "G\u00fcncellenmi\u015f uygulama ba\u015flat\u0131l\u0131yor...",
    "error": "G\u00fcncelleme tamamlanamad\u0131. L\u00fctfen uygulamadaki Yard\u0131m men\u00fcs\u00fcnden yeniden deneyin."
  },
  "it": {
    "prepare": "Preparazione dell\u2019aggiornamento. L\u2019applicazione si sta chiudendo; l\u2019installazione inizier\u00e0 non appena sar\u00e0 chiusa.",
    "consent": "Ora Windows chieder\u00e0 l\u2019autorizzazione a installare l\u2019aggiornamento. Consentila.",
    "install": "Installazione dell\u2019aggiornamento. Potrebbe richiedere un minuto; lascia aperta questa finestra.",
    "start": "Avvio della versione aggiornata dell\u2019applicazione...",
    "error": "L\u2019aggiornamento non \u00e8 stato completato. Riprova dal menu Aiuto dell\u2019applicazione."
  },
  "pl": {
    "prepare": "Przygotowywanie aktualizacji. Program jest zamykany; instalacja rozpocznie si\u0119 zaraz po jego zamkni\u0119ciu.",
    "consent": "System Windows poprosi teraz o zgod\u0119 na zainstalowanie aktualizacji. Wyra\u017a j\u0105, prosz\u0119.",
    "install": "Instalowanie aktualizacji. Mo\u017ce to potrwa\u0107 minut\u0119; pozostaw to okno otwarte.",
    "start": "Uruchamianie zaktualizowanej wersji programu...",
    "error": "Aktualizacja nie zosta\u0142a uko\u0144czona. Spr\u00f3buj ponownie z menu Pomoc w aplikacji."
  },
  "hi": {
    "prepare": "\u0905\u092a\u0921\u0947\u091f \u0915\u0940 \u0924\u0948\u092f\u093e\u0930\u0940 \u0939\u094b \u0930\u0939\u0940 \u0939\u0948\u0964 \u0910\u092a\u094d\u0932\u093f\u0915\u0947\u0936\u0928 \u092c\u0902\u0926 \u0939\u094b \u0930\u0939\u093e \u0939\u0948; \u0907\u0938\u0915\u0947 \u092c\u0902\u0926 \u0939\u094b\u0924\u0947 \u0939\u0940 \u0907\u0902\u0938\u094d\u091f\u0949\u0932\u0947\u0936\u0928 \u0936\u0941\u0930\u0942 \u0939\u094b \u091c\u093e\u090f\u0917\u093e\u0964",
    "consent": "Windows \u0905\u092c \u0905\u092a\u0921\u0947\u091f \u0907\u0902\u0938\u094d\u091f\u0949\u0932 \u0915\u0930\u0928\u0947 \u0915\u0940 \u0905\u0928\u0941\u092e\u0924\u093f \u092e\u093e\u0901\u0917\u0947\u0917\u093e\u0964 \u0915\u0943\u092a\u092f\u093e \u0905\u0928\u0941\u092e\u0924\u093f \u0926\u0947\u0902\u0964",
    "install": "\u0905\u092a\u0921\u0947\u091f \u0907\u0902\u0938\u094d\u091f\u0949\u0932 \u0939\u094b \u0930\u0939\u093e \u0939\u0948\u0964 \u0907\u0938\u092e\u0947\u0902 \u090f\u0915 \u092e\u093f\u0928\u091f \u0932\u0917 \u0938\u0915\u0924\u093e \u0939\u0948; \u0915\u0943\u092a\u092f\u093e \u0907\u0938 \u0935\u093f\u0902\u0921\u094b \u0915\u094b \u0916\u0941\u0932\u093e \u091b\u094b\u0921\u093c \u0926\u0947\u0902\u0964",
    "start": "\u0905\u092a\u0921\u0947\u091f \u0915\u093f\u092f\u093e \u0917\u092f\u093e \u0910\u092a\u094d\u0932\u093f\u0915\u0947\u0936\u0928 \u0936\u0941\u0930\u0942 \u0939\u094b \u0930\u0939\u093e \u0939\u0948...",
    "error": "\u0905\u092a\u0921\u0947\u091f \u092a\u0942\u0930\u093e \u0928\u0939\u0940\u0902 \u0939\u0941\u0906\u0964 \u0915\u0943\u092a\u092f\u093e \u0910\u092a \u0915\u0947 \u0938\u0939\u093e\u092f\u0924\u093e \u092e\u0947\u0928\u0942 \u0938\u0947 \u092b\u093f\u0930 \u0938\u0947 \u092a\u094d\u0930\u092f\u093e\u0938 \u0915\u0930\u0947\u0902\u0964"
  },
  "zh": {
    "prepare": "\u6b63\u5728\u51c6\u5907\u66f4\u65b0\u3002\u5e94\u7528\u7a0b\u5e8f\u6b63\u5728\u5173\u95ed\uff1b\u5173\u95ed\u540e\u5c06\u7acb\u5373\u5f00\u59cb\u5b89\u88c5\u3002",
    "consent": "Windows \u73b0\u5728\u4f1a\u8bf7\u6c42\u5b89\u88c5\u66f4\u65b0\u7684\u6743\u9650\u3002\u8bf7\u5141\u8bb8\u3002",
    "install": "\u6b63\u5728\u5b89\u88c5\u66f4\u65b0\u3002\u8fd9\u53ef\u80fd\u9700\u8981\u4e00\u5206\u949f\uff1b\u8bf7\u4fdd\u6301\u6b64\u7a97\u53e3\u6253\u5f00\u3002",
    "start": "\u6b63\u5728\u542f\u52a8\u66f4\u65b0\u540e\u7684\u5e94\u7528\u7a0b\u5e8f...",
    "error": "\u66f4\u65b0\u672a\u5b8c\u6210\u3002\u8bf7\u4ece\u5e94\u7528\u7a0b\u5e8f\u7684\u201c\u5e2e\u52a9\u201d\u83dc\u5355\u91cd\u8bd5\u3002"
  },
  "ja": {
    "prepare": "\u66f4\u65b0\u3092\u6e96\u5099\u3057\u3066\u3044\u307e\u3059\u3002\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u3092\u7d42\u4e86\u3057\u3066\u3044\u307e\u3059\u3002\u7d42\u4e86\u5f8c\u3059\u3050\u306b\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u3092\u958b\u59cb\u3057\u307e\u3059\u3002",
    "consent": "Windows \u304c\u66f4\u65b0\u306e\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u306e\u8a31\u53ef\u3092\u6c42\u3081\u307e\u3059\u3002\u8a31\u53ef\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    "install": "\u66f4\u65b0\u3092\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u3057\u3066\u3044\u307e\u3059\u30021 \u5206\u307b\u3069\u304b\u304b\u308b\u5834\u5408\u304c\u3042\u308a\u307e\u3059\u3002\u3053\u306e\u30a6\u30a3\u30f3\u30c9\u30a6\u306f\u958b\u3044\u305f\u307e\u307e\u306b\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
    "start": "\u66f4\u65b0\u3055\u308c\u305f\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u3092\u8d77\u52d5\u3057\u3066\u3044\u307e\u3059...",
    "error": "\u66f4\u65b0\u304c\u5b8c\u4e86\u3057\u307e\u305b\u3093\u3067\u3057\u305f\u3002\u30a2\u30d7\u30ea\u30b1\u30fc\u30b7\u30e7\u30f3\u306e\uff3b\u30d8\u30eb\u30d7\uff3d\u30e1\u30cb\u30e5\u30fc\u304b\u3089\u3082\u3046\u4e00\u5ea6\u304a\u8a66\u3057\u304f\u3060\u3055\u3044\u3002"
  },
  "hu": {
    "prepare": "A friss\u00edt\u00e9s el\u0151k\u00e9sz\u00edt\u00e9se folyamatban van. Az alkalmaz\u00e1s bez\u00e1rul; a telep\u00edt\u00e9s a bez\u00e1r\u00e1s ut\u00e1n azonnal elindul.",
    "consent": "A Windows most enged\u00e9lyt k\u00e9r a friss\u00edt\u00e9s telep\u00edt\u00e9s\u00e9hez. K\u00e9rj\u00fck, enged\u00e9lyezze.",
    "install": "A friss\u00edt\u00e9s telep\u00edt\u00e9se folyamatban van. Ez k\u00f6r\u00fclbel\u00fcl egy percig tarthat; hagyja nyitva ezt az ablakot.",
    "start": "A friss\u00edtett alkalmaz\u00e1s ind\u00edt\u00e1sa...",
    "error": "A friss\u00edt\u00e9s nem fejez\u0151d\u00f6tt be. Pr\u00f3b\u00e1lja \u00fajra az alkalmaz\u00e1s S\u00fag\u00f3 men\u00fcj\u00e9b\u0151l."
  }
}
'@

function Get-UpdateMessages {
    param([string]$Code)
    try {
        $catalog = $UpdateMessagesJson | ConvertFrom-Json
        $normalized = if ($Code) { $Code.Trim().ToLowerInvariant() } else { "en" }
        $normalized = ($normalized -split '[-_]')[0]
        $property = $catalog.PSObject.Properties[$normalized]
        if (-not $property) { $property = $catalog.PSObject.Properties["en"] }
        return $property.Value
    } catch {
        return [PSCustomObject]@{
            prepare = "Preparing the update. Accessible IPTV Client is closing; installation will start as soon as it closes."
            install = "Installing the update. This can take a minute; please leave this window open."
            start = "Starting the updated Accessible IPTV Client..."
            consent = "Windows will now ask for permission to install the update. Please allow it."
            error = "The update did not finish. Please try again from the Help menu in the application."
        }
    }
}

$updateMessages = Get-UpdateMessages -Code $Language

# The app closes before the installer runs, so for the length of the update
# nothing was on screen: the window vanished, the installer worked silently, and
# a screen-reader user was left with no idea whether anything was happening or
# whether the app was ever coming back. This helper owns a small status window
# instead. It cannot be in the app itself (the app has to exit for the install
# to start), so it is shown here, kept up through the installer and the restart,
# and closed only once the new app has actually started.
#
# A WinForms window only stays alive while something pumps its messages, and
# this script spends nearly all of its time waiting - for the app to exit, for
# the installer to finish, for the restarted app to prove it survived. Plain
# Start-Sleep pumps nothing, so the window used to go unresponsive within
# seconds: Windows ghosts it, paints it blank and stops it answering the screen
# reader, which is exactly the "the window disappears" the update was supposed
# to stop. Every wait below therefore goes through Wait-Pumped.
function Show-UpdateStatus {
    param([string]$Message)
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        [System.Windows.Forms.Application]::EnableVisualStyles()
    } catch {
        Write-Log "Could not load WinForms for the status window: $($_.Exception.Message)"
        return $null
    }
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen
    $workArea = $screen.WorkingArea
    $form = New-Object System.Windows.Forms.Form
    # The title carries the message from the start, not just from the first
    # update. Nothing in this window can take focus, so the window itself is
    # what NVDA reads when it appears - its title - and a generic title meant
    # the first message ("Preparing the update...") was never spoken at all.
    $form.Text = "Accessible IPTV Client - $Message"
    $form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $form.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
    $form.Location = New-Object System.Drawing.Point(($workArea.Left + 60), ($workArea.Top + 60))
    $form.Size = New-Object System.Drawing.Size(440, 190)
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ShowInTaskbar = $true
    $form.TopMost = $true

    $statusLabel = New-Object System.Windows.Forms.Label
    $statusLabel.Name = "StatusLabel"
    $statusLabel.Text = $Message
    $statusLabel.AutoSize = $false
    $statusLabel.SetBounds(16, 16, 392, 76)
    $statusLabel.TabIndex = 0
    $form.Controls.Add($statusLabel)

    # A marquee bar is the one thing that says "still working" without any
    # text to re-read, and it keeps the window visibly alive between steps.
    $progress = New-Object System.Windows.Forms.ProgressBar
    $progress.Name = "StatusProgress"
    $progress.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
    $progress.MarqueeAnimationSpeed = 30
    $progress.SetBounds(16, 100, 392, 20)
    $progress.TabIndex = 1
    $form.Controls.Add($progress)

    try {
        $form.Show()
        $form.Activate()
        [System.Windows.Forms.Application]::DoEvents()
    } catch { }
    return $form
}

function Update-StatusMessage {
    param($Window, [string]$Message)
    if (-not $Window) { return }
    try {
        $Window.Controls["StatusLabel"].Text = $Message
        # The title carries the same text so NVDA+T reports where the update
        # has got to, and so the taskbar button is not just "Updating...".
        $Window.Text = "Accessible IPTV Client - $Message"
        $Window.Refresh()
        [System.Windows.Forms.Application]::DoEvents()
    } catch {
        Write-Log "Status window update failed: $($_.Exception.Message)"
    }
}

# Every failure ends here. The status window has nothing focusable, so an
# error left in it for a few seconds was easy to miss entirely. If the app on
# disk still starts, start it: it reports the failed update itself, in its own
# language, with the log path. Only if it cannot start does this helper show a
# message box, which takes focus and waits for OK.
# What each Inno Setup exit code means, from the Inno Setup documentation.
$InnoExitCodes = @{
    1 = "Setup failed to initialize."
    2 = "Setup was cancelled before the installation started."
    3 = "A fatal error occurred while preparing the installation."
    4 = "A fatal error occurred during the installation."
    5 = "The installation was cancelled or aborted, for example because a file could not be replaced."
    6 = "Setup was terminated by another process."
    7 = "Setup found a problem that stops the installation, for example files in use."
    8 = "Setup needs Windows to restart before it can install."
}

# The lines of the Inno Setup log that say what went wrong: the message box
# Setup answered by itself in silent mode (it defaults to Abort), or failing
# that the last lines that mention an error.
function Get-InstallerError {
    param([string]$Path)
    try {
        if (-not (Test-Path -LiteralPath $Path)) { return "" }
        $lines = @(Get-Content -LiteralPath $Path -ErrorAction Stop)
    } catch {
        return ""
    }
    $picked = @()
    for ($i = $lines.Count - 1; $i -ge 0; $i--) {
        if ($lines[$i] -match 'Defaulting to \w+ for suppressed message box|Message box \(') {
            $picked += $lines[$i]
            for ($j = $i + 1; $j -lt $lines.Count -and $lines[$j] -match '^\s{4,}'; $j++) {
                $picked += $lines[$j]
            }
            break
        }
    }
    if (-not $picked) {
        $picked = @($lines | Where-Object {
            $_ -match '(?i)error|fail|fatal|denied|in use' -and $_ -notmatch '(?i)successfully'
        } | Select-Object -Last 4)
    }
    $text = (($picked | ForEach-Object { ($_ -replace '^\d{4}-\d\d-\d\d [\d:.]+\s+', '').Trim() }) |
        Where-Object { $_ }) -join " "
    if ($text.Length -gt 600) { $text = $text.Substring(0, 600) + "..." }
    return $text
}

function Write-UpdateResult {
    param([string]$Kind, [string]$Reason, $ExitCode = $null, [string]$InstallerError = "")
    try {
        $result = [ordered]@{
            status          = "failed"
            kind            = $Kind
            reason          = $Reason
            exit_code       = $ExitCode
            installer_error = $InstallerError
            time            = (Get-Date).ToString("o")
        }
        [System.IO.File]::WriteAllText($resultPath, ($result | ConvertTo-Json -Compress), (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        Write-Log "Could not write the update result: $($_.Exception.Message)"
    }
}

function Complete-FailedUpdate {
    param($Window, [string]$Reason, [int]$Code = 1, [string]$Kind = "other",
          $ExitCode = $null, [string]$InstallerLog = "")
    Write-Log "Update failed: $Reason"
    $installerError = ""
    if ($InstallerLog) {
        $installerError = Get-InstallerError -Path $InstallerLog
        if ($installerError) { Write-Log "Installer error: $installerError" }
    }
    Write-UpdateResult -Kind $Kind -Reason $Reason -ExitCode $ExitCode -InstallerError $installerError
    Update-StatusMessage -Window $Window -Message $updateMessages.error
    $restarted = $false
    $oldExe = Join-Path $InstallDir $ExeName
    if (Test-Path -LiteralPath $oldExe) {
        Write-Log "Starting the existing app so it can report the failure: $oldExe"
        $restarted = Start-AppAfterUpdate -ExePath $oldExe -WorkDir $InstallDir -Arguments $RestartArgs -Window $Window
    }
    if (-not $restarted) {
        try {
            $text = $updateMessages.error + [Environment]::NewLine + [Environment]::NewLine + $logPath
            if ($Window) {
                [void][System.Windows.Forms.MessageBox]::Show($Window, $text, "Accessible IPTV Client", "OK", "Error")
            } else {
                Add-Type -AssemblyName System.Windows.Forms
                [void][System.Windows.Forms.MessageBox]::Show($text, "Accessible IPTV Client", "OK", "Error")
            }
        } catch {
            Write-Log "Could not show the failure message: $($_.Exception.Message)"
        }
    }
    Close-StatusWindow -Window $Window
    exit $Code
}

# Sleep while keeping the status window painting and answering.
function Wait-Pumped {
    param([int]$Milliseconds, $Window)
    $deadline = (Get-Date).AddMilliseconds($Milliseconds)
    while ((Get-Date) -lt $deadline) {
        if ($Window) {
            try { [System.Windows.Forms.Application]::DoEvents() } catch { }
        }
        Start-Sleep -Milliseconds 50
    }
}

# Wait for a process, pumping the status window, up to an optional cap.
function Wait-ForProcessExit {
    param($Process, $Window, [int]$TimeoutSeconds = 0)
    $deadline = if ($TimeoutSeconds -gt 0) { (Get-Date).AddSeconds($TimeoutSeconds) } else { $null }
    while (-not $Process.HasExited) {
        if ($deadline -and (Get-Date) -ge $deadline) { return $false }
        Wait-Pumped -Milliseconds 200 -Window $Window
    }
    return $true
}

function Close-StatusWindow {
    param($Window)
    if (-not $Window) { return }
    try { $Window.Close(); $Window.Dispose() } catch { }
}

function Start-AppAfterUpdate {
    param(
        [string]$ExePath,
        [string]$WorkDir,
        [string]$Arguments = "",
        $Window = $null
    )

    # A silent restart failure is the worst outcome there is for a screen-reader
    # user: the update succeeded, the app is simply gone, and nothing on screen
    # says why. So every attempt is verified - a process that dies within a few
    # seconds counts as a failure, not a success - and the last resort hands the
    # launch to Explorer, which starts the app from the shell instead of from
    # this helper's own process tree.
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $app = $null
        try {
            $startArgs = @{
                FilePath         = $ExePath
                WorkingDirectory = $WorkDir
                PassThru         = $true
            }
            if ($Arguments) { $startArgs['ArgumentList'] = $Arguments }
            $app = Start-Process @startArgs
        } catch {
            Write-Log "Restart attempt $attempt could not launch the app: $($_.Exception.Message)"
        }
        if ($app) {
            # Long enough to get past DLL loading, where a broken install dies.
            for ($tick = 0; $tick -lt 20 -and -not $app.HasExited; $tick++) {
                Wait-Pumped -Milliseconds 250 -Window $Window
            }
            if (-not $app.HasExited) {
                Write-Log "App restarted (PID $($app.Id))."
                return $true
            }
            Write-Log "Restart attempt $attempt exited immediately with code $($app.ExitCode)."
        }
        Wait-Pumped -Milliseconds 2000 -Window $Window
    }

    try {
        Write-Log "Falling back to Explorer to start the app."
        Start-Process -FilePath "explorer.exe" -ArgumentList "`"$ExePath`""
        return $true
    } catch {
        Write-Log "Explorer fallback failed: $($_.Exception.Message)"
    }
    Write-Log "Could not restart the app after the update."
    return $false
}

$statusWindow = Show-UpdateStatus -Message $updateMessages.prepare

# The app holds its own progress dialog open until this file appears, so the
# two windows overlap and the screen is never empty. Written only once the
# window really is showing - PowerShell plus WinForms takes a second or two to
# start, and that gap is what used to look like the update window vanishing.
if ($ReadyFile) {
    try {
        New-Item -ItemType File -Path $ReadyFile -Force | Out-Null
        Write-Log "Signalled the app that the status window is up: $ReadyFile"
    } catch {
        Write-Log "Could not write the ready file: $($_.Exception.Message)"
    }
}

Write-Log "Updater started. Waiting for PID $ParentPid."

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Wait-Pumped -Milliseconds 500 -Window $statusWindow
}

$parentProcess = Get-Process -Id $ParentPid -ErrorAction SilentlyContinue
if ($parentProcess) {
    Write-Log "Process $ParentPid did not exit within timeout; terminating it."
    Stop-Process -Id $ParentPid -Force -ErrorAction SilentlyContinue
    Wait-Pumped -Milliseconds 1000 -Window $statusWindow
}

# Kill any processes running from the install directory. The app itself is
# normally the only one, but a recording interrupted while FFmpeg was
# finalising can leave the bundled ffmpeg.exe alive after the app exits. That
# process holds its executable open on Windows, preventing an installer or
# portable directory-swap update from replacing it.
Write-Log "Scanning for processes locking $InstallDir..."
try {
    $targetProcessName = [System.IO.Path]::GetFileNameWithoutExtension($ExeName)
    $installPrefix = $InstallDir.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    # ffmpeg.exe is bundled alongside IPTVClient.exe (main.spec), so constrain
    # cleanup by the image path below; never terminate an unrelated FFmpeg.
    $targetProcessNames = @($targetProcessName, "ffmpeg") | Select-Object -Unique
    $candidateProcesses = Get-Process -Name $targetProcessNames -ErrorAction SilentlyContinue
    $zombies = $candidateProcesses | Where-Object {
        try {
            $_.MainModule.FileName.StartsWith($installPrefix, [System.StringComparison]::OrdinalIgnoreCase)
        } catch {
            $false
        }
    }
    foreach ($proc in $zombies) {
        if ($proc.Id -ne $PID -and $proc.Id -ne $ParentPid) {
            Write-Log "Stopping process locking the install directory: $($proc.Name) (PID $($proc.Id))"
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Wait-Pumped -Milliseconds 500 -Window $statusWindow
} catch {
    Write-Log "Warning: Failed to scan/kill zombie processes: $($_.Exception.Message)"
}

if ($InstallerPath) {
    if (-not (Test-Path -LiteralPath $InstallerPath)) {
        Complete-FailedUpdate -Window $statusWindow -Reason "Installer missing: $InstallerPath"
    }

    $installerLog = Join-Path $env:TEMP "AccessibleIPTVClient_installer.log"
    $installerArgs = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /LOG=`"$installerLog`" /DIR=`"$InstallDir`""
    Write-Log "Launching installer update: $InstallerPath $installerArgs"
    Update-StatusMessage -Window $statusWindow -Message $updateMessages.consent
    $proc = $null
    try {
        # Program Files needs elevation. Start-Process -Verb RunAs gave the
        # consent request no owner window, and a hidden background process
        # asking without one gets a flashing taskbar button instead of the
        # UAC prompt - which a screen reader user never hears, so the update
        # sat there until the user gave up (issue #26). Owning the request
        # with the status window, which the app let us bring to the front,
        # puts the real prompt on screen.
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $InstallerPath
        $psi.Arguments = $installerArgs
        $psi.WorkingDirectory = $env:TEMP
        $psi.UseShellExecute = $true
        $psi.Verb = "runas"
        if ($statusWindow) {
            $psi.ErrorDialog = $true
            $psi.ErrorDialogParentHandle = $statusWindow.Handle
            try { $statusWindow.Activate() } catch { }
        }
        $proc = [System.Diagnostics.Process]::Start($psi)
    } catch {
        $inner = $_.Exception
        while ($inner.InnerException) { $inner = $inner.InnerException }
        if ($inner -is [System.ComponentModel.Win32Exception] -and $inner.NativeErrorCode -eq 1223) {
            Complete-FailedUpdate -Window $statusWindow -Kind "declined" -Reason "Permission to run the installer was declined."
        }
        Complete-FailedUpdate -Window $statusWindow -Kind "launch" -Reason "Failed to launch installer: $($inner.Message)"
    }
    if (-not $proc) {
        Complete-FailedUpdate -Window $statusWindow -Kind "launch" -Reason "The installer did not start."
    }
    Write-Log "Installer running (PID $($proc.Id)); its log is $installerLog"
    Update-StatusMessage -Window $statusWindow -Message $updateMessages.install

    # Pumped, and capped: a silent installer that never returns must still end
    # in a message rather than a status window that sits there for ever.
    if (-not (Wait-ForProcessExit -Process $proc -Window $statusWindow -TimeoutSeconds 900)) {
        Complete-FailedUpdate -Window $statusWindow -Kind "timeout" -InstallerLog $installerLog -Reason "Installer still running after 15 minutes; see $installerLog"
    }
    # Settle the process object so ExitCode is populated before it is read.
    try { $proc.WaitForExit() } catch { }
    $installerExit = $proc.ExitCode
    if ($installerExit -ne 0) {
        $meaning = if ($null -ne $installerExit -and $InnoExitCodes.ContainsKey([int]$installerExit)) { " " + $InnoExitCodes[[int]$installerExit] } else { "" }
        Complete-FailedUpdate -Window $statusWindow -Code ([int]$installerExit) -Kind "installer" -ExitCode $installerExit -InstallerLog $installerLog -Reason "Installer failed with exit code $installerExit.$meaning See $installerLog"
    }
    Write-Log "Installer finished successfully."

    $exePath = Join-Path $InstallDir $ExeName
    if (-not (Test-Path -LiteralPath $exePath)) {
        Complete-FailedUpdate -Window $statusWindow -Reason "Executable not found after installer update: $exePath"
    }
    Update-StatusMessage -Window $statusWindow -Message $updateMessages.start
    Write-Log "Restarting app after installer update: $exePath"
    $restarted = Start-AppAfterUpdate -ExePath $exePath -WorkDir $InstallDir -Arguments $RestartArgs -Window $statusWindow
    Write-Log "Installer updater completed."
    Close-StatusWindow -Window $statusWindow
    if ($restarted) { exit 0 }
    exit 2
}

if (-not (Test-Path -LiteralPath $StagingDir)) {
    Complete-FailedUpdate -Window $statusWindow -Reason "Staging directory missing: $StagingDir"
}

$parentDir = Split-Path -Parent $InstallDir
if ($parentDir -and -not (Test-Path -LiteralPath $parentDir)) {
    New-Item -ItemType Directory -Path $parentDir | Out-Null
}

Update-StatusMessage -Window $statusWindow -Message $updateMessages.install

if (Test-Path -LiteralPath $BackupDir) {
    Remove-Item -LiteralPath $BackupDir -Recurse -Force
}

try {
    if (Test-Path -LiteralPath $InstallDir) {
        Move-Item -LiteralPath $InstallDir -Destination $BackupDir -Force
        Write-Log "Moved current install to backup: $BackupDir"
    }
} catch {
    Complete-FailedUpdate -Window $statusWindow -Reason "Failed to move install to backup: $($_.Exception.Message)"
}

try {
    Move-Item -LiteralPath $StagingDir -Destination $InstallDir -Force
    Write-Log "Installed update to $InstallDir"

    # Portable zip updates replace the app directory; preserve the local config
    # beside the new executable when the previous portable copy had one.
    $oldConfig = Join-Path $BackupDir "iptvclient.conf"
    $newConfig = Join-Path $InstallDir "iptvclient.conf"
    if ((Test-Path -LiteralPath $oldConfig) -and -not (Test-Path -LiteralPath $newConfig)) {
        try {
            Copy-Item -LiteralPath $oldConfig -Destination $newConfig -Force
            Write-Log "Preserved portable configuration in install directory."
        } catch {
            Write-Log "Failed to preserve portable configuration: $($_.Exception.Message)"
        }
    }

    # Preserve pre-portable AppData configs as a fallback for users updating
    # from builds that still stored portable settings in the roaming profile.
    $roamingDir = Join-Path $env:APPDATA "AccessibleIPTVClient"
    $roamingConfig = Join-Path $roamingDir "iptvclient.conf"
    if ((Test-Path -LiteralPath $roamingConfig) -and -not (Test-Path -LiteralPath $newConfig)) {
        try {
            Copy-Item -LiteralPath $roamingConfig -Destination $newConfig -Force
            Write-Log "Migrated roaming configuration to portable install directory."
        } catch {
            Write-Log "Failed to migrate configuration: $($_.Exception.Message)"
        }
    }
} catch {
    Write-Log "Failed to move staging into place: $($_.Exception.Message)"
    if ((Test-Path -LiteralPath $BackupDir) -and -not (Test-Path -LiteralPath $InstallDir)) {
        try {
            Move-Item -LiteralPath $BackupDir -Destination $InstallDir -Force
            Write-Log "Rollback completed."
        } catch {
            Write-Log "Rollback failed: $($_.Exception.Message)"
        }
    }
    Complete-FailedUpdate -Window $statusWindow -Reason "Could not put the update in place."
}

$exePath = Join-Path $InstallDir $ExeName
if (-not (Test-Path -LiteralPath $exePath)) {
    Write-Log "Executable not found after update: $exePath"
    if (Test-Path -LiteralPath $BackupDir) {
        try {
            Remove-Item -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
            Move-Item -LiteralPath $BackupDir -Destination $InstallDir -Force
            Write-Log "Rolled back to previous version because the new executable was missing."
        } catch {
            Write-Log "Rollback failed: $($_.Exception.Message)"
        }
    }
    Complete-FailedUpdate -Window $statusWindow -Reason "The updated executable was missing."
}

# Clear the backup before restarting, not after. A recursive delete of a
# directory tree right beside the install is heavy disk work, and it used to run
# while the freshly started app was still loading its own DLLs out of that same
# install directory.
if (Test-Path -LiteralPath $BackupDir) {
    try {
        Write-Log "Removing backup directory: $BackupDir"
        Remove-Item -LiteralPath $BackupDir -Recurse -Force -ErrorAction Stop
        Write-Log "Backup directory removed successfully."
    } catch {
        Write-Log "Failed to remove backup directory: $($_.Exception.Message)"
    }
}

Update-StatusMessage -Window $statusWindow -Message $updateMessages.start
Write-Log "Restarting app: $exePath"
$restarted = Start-AppAfterUpdate -ExePath $exePath -WorkDir $InstallDir -Arguments $RestartArgs -Window $statusWindow

Write-Log "Updater completed."
Close-StatusWindow -Window $statusWindow
if ($restarted) { exit 0 }
exit 2
