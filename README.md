# سحر 0.1.19

![Sahar banner](assets/banner.png)

**سامانه مدیریت Xray / VLESS با معماری Master / Agent و پنل تلگرام**  
**Telegram-first Xray / VLESS management platform with master-agent architecture**

![version](https://img.shields.io/badge/version-0.1.19-8b5cf6)
![platform](https://img.shields.io/badge/linux-Debian%20%7C%20Ubuntu%20%7C%20Alpine-0ea5e9)
![profiles](https://img.shields.io/badge/VLESS-Reality%20%2B%20Simple-22c55e)
![panel](https://img.shields.io/badge/Panel-Telegram-2563eb)

> **نکته مهم:** این پروژه فقط روی **Ubuntu / Debian / Alpine** پشتیبانی می‌شود و نصب باید با **دسترسی root** انجام شود.  
> **Important:** This project supports **Ubuntu / Debian / Alpine** only and installation must run with **root** privileges.

---

## معرفی پروژه | Project overview

**سحر** برای این ساخته شده که مدیریت Xray را از حالت دستی بیرون بیاورد و آن را به یک جریان متمرکز تبدیل کند.

اجزای اصلی پروژه:
- **Master** برای مدیریت مرکزی، دیتابیس، بات و subscription
- **Agent** برای اعمال تغییرات Xray روی هر VPS
- **Telegram Bot** برای مدیریت روزمره
- **Subscription ثابت** برای هر کاربر
- **Cloudflare DNS automation** به‌صورت اختیاری
- **SSH provisioning** برای نصب Agent از داخل بات

در معماری واقعی پروژه:
- Master مرکز کنترل است
- Agent روی هر نود اجرا می‌شود
- بات تلگرام به Master وصل است
- هر کاربر یک subscription token ثابت دارد
- در حالت `dual`، subscription هر دو پروفایل Simple و Reality را برمی‌گرداند

---

## این بسته شامل چه چیزهایی است؟ | Bundle contents

این فایل ZIP شامل این موارد است:
- `install.sh` شروع نصب
- `install_master.sh` نصب Master
- `install_agent.sh` نصب Agent
- `master_app/` کدهای Master
- `agent_app/` کدهای Agent
- `assets/` فایل‌های تصویری README
- `VERSION` نسخه بسته
- `PATCH_NOTES.txt` یادداشت تغییرات

---

## نصب از روی فایل ZIP | Install from the ZIP bundle

اگر همین بسته را دانلود کرده‌ای، روش استاندارد نصب این است:

```bash
unzip sahar_0.1.19_single_installer.zip && cd sahar_0.1.19_single_installer && sudo sh install.sh
```

برای نصب مستقیم Master:

```bash
unzip sahar_0.1.19_single_installer.zip && cd sahar_0.1.19_single_installer && sudo sh install.sh master
```

برای نصب مستقیم Agent:

```bash
unzip sahar_0.1.19_single_installer.zip && cd sahar_0.1.19_single_installer && sudo sh install.sh agent
```

اگر آرگومان ندهی، installer از خودت می‌پرسد که می‌خواهی Master نصب شود یا Agent.

---

## نصب مستقیم از GitHub با یک خط دستور | One-line direct install from GitHub

آدرس واقعی پروژه:

```text
https://github.com/PooyanGhorbani/Sahar
```

اگر بخواهی مستقیم از خود GitHub نصب کنی و هیچ ZIPی را دستی دانلود نکنی، این دستورها را همان‌طور که هستند کپی کن.

### نصب Master از GitHub

```bash
git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sudo sh install.sh master
```

### نصب Agent از GitHub

```bash
git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sudo sh install.sh agent
```

### اگر `git` روی سرور نصب نبود

می‌توانی بدون `git` هم مستقیم از GitHub نصب کنی:

#### Master

```bash
curl -fsSL https://github.com/PooyanGhorbani/Sahar/archive/refs/heads/main.zip -o /tmp/sahar.zip && rm -rf /tmp/sahar-src && mkdir -p /tmp/sahar-src && unzip -q /tmp/sahar.zip -d /tmp/sahar-src && cd /tmp/sahar-src/Sahar-main && sudo sh install.sh master
```

#### Agent

```bash
curl -fsSL https://github.com/PooyanGhorbani/Sahar/archive/refs/heads/main.zip -o /tmp/sahar.zip && rm -rf /tmp/sahar-src && mkdir -p /tmp/sahar-src && unzip -q /tmp/sahar.zip -d /tmp/sahar-src && cd /tmp/sahar-src/Sahar-main && sudo sh install.sh agent
```

### نکته مهم

- هر دو دستور بالا آخرین نسخه branch `main` را نصب می‌کنند
- اگر پروژه را در مسیر دیگری می‌خواهی، فقط `/opt/sahar` را عوض کن
- اگر دستور را با کاربر عادی اجرا می‌کنی، بخش `sudo` باید روی آن سرور سالم و فعال باشد
- اگر از قبل پوشه `/opt/sahar` وجود دارد، قبل از clone آن را پاک کن یا مسیر دیگری بده

---

## سیستم‌عامل‌های پشتیبانی‌شده | Supported operating systems

این installer خانواده سیستم‌عامل را خودکار تشخیص می‌دهد:
- **Ubuntu / Debian**
- **Alpine**

همچنین ابزار سرویس مناسب را خودش انتخاب می‌کند:
- روی Debian/Ubuntu از `systemd`
- روی Alpine از `OpenRC`

یعنی لازم نیست برای systemd یا OpenRC چیزی را دستی تغییر بدهی.

---

## معماری پروژه | Architecture

### Master
Master این بخش‌ها را اجرا می‌کند:
- Telegram Bot
- SQLite Database
- Subscription HTTP Service
- Scheduler
- Backup Manager
- Cloudflare bootstrap/manager
- SSH Provisioner

Master می‌تواند فقط نقش مدیریتی داشته باشد یا در زمان نصب، به‌صورت اختیاری Local Node هم روی همان سرور فعال شود.

### Agent
Agent روی هر VPS اجرا می‌شود و این کارها را انجام می‌دهد:
- مدیریت کاربران Xray
- فعال/غیرفعال کردن کاربر
- حذف و اضافه کاربر
- بازخوانی و ری‌استارت Xray
- خواندن آمار مصرف از Xray API
- گزارش سلامت نود به Master

### پنل تلگرام | Telegram panel
بات تلگرام برای عملیات روزمره استفاده می‌شود؛ مثل:
- ساخت کاربر
- تغییر پلن
- گرفتن لینک و QR
- افزودن سرور
- بررسی سلامت
- حذف سرور
- اجرای بعضی عملیات نگهداری

---

## پروفایل‌ها و خروجی کاربر | User profiles and output

برای هر کاربر یک **subscription ثابت** ساخته می‌شود. این یعنی:
- لینک subscription کاربر ثابت می‌ماند
- با اضافه یا حذف شدن سرورها، خود لینک عوض نمی‌شود
- فقط محتوای subscription به‌روزرسانی می‌شود

پروفایل‌هایی که پروژه می‌سازد:
- `VLESS | Simple`
- `VLESS | Reality`

در نسخه فعلی:
- subscription هر دو پروفایل را ارائه می‌کند
- لینک و QR اصلی در حالت `dual` روی پروفایل Reality قرار می‌گیرند

---

## شروع سریع | Quick start

### حالت 1: فقط یک VPS داری
اگر فقط یک سرور داری، معمولاً بهترین حالت این است که **Master** را نصب کنی و هنگام نصب، **Local Node** را هم فعال کنی.

```bash
unzip sahar_0.1.19_single_installer.zip && cd sahar_0.1.19_single_installer && sudo sh install.sh master
```

وقتی این سؤال را دیدی:

```text
Enable local VPN node on this master server? [Y/n]
```

اگر `Y` بدهی، همان سرور هم Master می‌شود و هم Local Node.

### حالت 2: چند VPS داری
روی سرور اصلی:

```bash
sudo sh install.sh master
```

روی هر سرور اضافه:

```bash
sudo sh install.sh agent
```

---

## در نصب Master چه چیزهایی پرسیده می‌شود؟ | Master installer prompts

`install_master.sh` به‌صورت تعاملی این موارد را می‌پرسد:
- Telegram bot token
- Admin chat IDs
- فاصله اجرای scheduler
- timeout ارتباط با Agent
- آستانه هشدار زمان و مصرف
- تنظیمات backup
- `subscription public base URL`
- تنظیمات bind سرویس subscription
- فعال/غیرفعال بودن Cloudflare
- اگر Cloudflare فعال باشد:
  - دامنه اصلی
  - base subdomain
  - API token
- فعال/غیرفعال بودن Local Node
- اگر Local Node فعال باشد:
  - نام نود
  - IP یا دامنه عمومی
  - تنظیمات Reality
  - پورت‌ها
  - توکن Local Agent

**پورت پیش‌فرض Subscription:** `8090`

---

## در نصب Agent چه چیزهایی پرسیده می‌شود؟ | Agent installer prompts

`install_agent.sh` این موارد را می‌پرسد:
- نام Agent
- IP یا دامنه عمومی
- `REALITY serverName/SNI`
- `REALITY dest`
- fingerprint
- پورت Simple
- پورت Reality
- پورت Xray API
- آدرس bind و پورت Agent API
- `Allowed source IPs/CIDRs`
- `Agent API token`

**پورت پیش‌فرض Agent API:** `8787`  
**پورت پیش‌فرض Simple:** `443`  
**پورت پیش‌فرض Reality:** `8443`  
**پورت پیش‌فرض Xray API:** `10085`

---

## افزودن Agent با SSH از داخل بات | SSH provisioning from Telegram

یکی از قابلیت‌های مهم پروژه این است که Master می‌تواند Agent را از داخل بات روی VPS جدید نصب کند.

wizard این اطلاعات را می‌گیرد:
- نام سرور
- IP یا دامنه SSH
- پورت SSH
- نام کاربری SSH
- رمز SSH

بعد Master این کارها را انجام می‌دهد:
- اتصال SSH برقرار می‌کند
- فایل‌های لازم را به سرور مقصد می‌فرستد
- نصب Agent را به‌صورت non-interactive اجرا می‌کند
- health check می‌گیرد
- سرور را در دیتابیس ثبت می‌کند
- اگر Cloudflare فعال باشد، رکورد DNS هم می‌سازد

### نکته مهم درباره SSH provisioning
- اگر با `root` وصل شوی، جریان نصب مستقیم‌تر است
- اگر با کاربر عادی وصل شوی، آن کاربر باید **sudo فعال و سالم** داشته باشد
- اگر `sudo` روی سرور مقصد نصب نباشد یا آن یوزر sudoer نباشد، نصب خودکار fail می‌شود

---

## اتصال خودکار سرور به Cloudflare دقیقاً چگونه کار می‌کند؟ | How automatic Cloudflare connection works

این بخش مهم است چون Cloudflare در این پروژه **Tunnel** یا **Proxy کامل** راه‌اندازی نمی‌کند. کاری که انجام می‌دهد **مدیریت رکورد DNS** است.

### پروژه دقیقاً چه کاری می‌کند؟
اگر Cloudflare را در زمان نصب Master فعال کنی، Master می‌تواند برای هر سروری که اضافه می‌کنی، یک رکورد DNS از نوع `A` داخل همان zone بسازد یا به‌روزرسانی کند.

یعنی اگر این ورودی‌ها را بدهی:
- دامنه اصلی: `example.com`
- base subdomain: `vpn`
- نام سرور: `ir1`
- IP واقعی سرور: `203.0.113.10`

پروژه رکوردی شبیه این می‌سازد:

```text
ir1.vpn.example.com -> 203.0.113.10
```

اگر base subdomain خالی باشد، خروجی این‌طور می‌شود:

```text
ir1.example.com -> 203.0.113.10
```

### چه زمانی این اتفاق می‌افتد؟
Cloudflare automation در این پروژه معمولاً در این نقاط استفاده می‌شود:
1. هنگام نصب Master، token و zone تنظیم می‌شود
2. وقتی سرور جدید را با SSH از داخل بات اضافه می‌کنی
3. وقتی سرور در دیتابیس ثبت شد و IP آن مشخص شد
4. Master از Cloudflare API رکورد DNS را create/update می‌کند
5. اگر بعداً سرور را حذف کنی، پروژه تلاش می‌کند رکورد DNS را هم پاک کند

### روند کامل اتصال خودکار سرور به Cloudflare به زبان ساده
1. روی Cloudflare یک API token می‌سازی که دسترسی `Zone Read` و `DNS Write` داشته باشد
2. هنگام نصب Master، دامنه اصلی، base subdomain و token را وارد می‌کنی
3. Master zone مربوط به دامنه را پیدا می‌کند و اطلاعات Cloudflare را در config نگه می‌دارد
4. وقتی از داخل بات سرور جدید را اضافه می‌کنی، Master بعد از نصب Agent، IP واقعی آن سرور را به دست می‌آورد
5. Master با نام سرور یک hostname می‌سازد؛ مثلاً برای `ir1` و base subdomain برابر `vpn`، خروجی می‌شود `ir1.vpn.example.com`
6. اگر رکورد از قبل وجود داشته باشد، آن را update می‌کند؛ اگر وجود نداشته باشد، آن را create می‌کند
7. نام نهایی DNS داخل دیتابیس ذخیره می‌شود و می‌تواند در خروجی‌ها، subscription یا public host همان سرور استفاده شود

### مثال عملی کامل
فرض کن این اطلاعات را وارد کرده‌ای:
- دامنه اصلی: `example.com`
- base subdomain: `vpn`
- نام سرور: `de1`
- IP واقعی سرور: `198.51.100.25`

خروجی نهایی Cloudflare این می‌شود:

```text
de1.vpn.example.com -> 198.51.100.25
```

اگر بعداً IP همین سرور عوض شود و دوباره provisioning یا update انجام دهی، پروژه رکورد را روی IP جدید sync می‌کند.

### چه چیزهایی لازم داری؟
برای اینکه این بخش درست کار کند، باید این پیش‌نیازها را داشته باشی:
- دامنه‌ات داخل Cloudflare باشد
- API token معتبر بسازی
- token حداقل این دسترسی‌ها را داشته باشد:
  - `Zone Read`
  - `DNS Write`
- دامنه‌ای که وارد می‌کنی، همان zone واقعی Cloudflare باشد

### هنگام نصب Master چه چیزهایی وارد می‌کنی؟
اگر به سؤال زیر جواب `Y` بدهی:

```text
Enable Cloudflare DNS automation? [Y/n]
```

installer این موارد را می‌پرسد:
- `Cloudflare domain name` مثل `example.com`
- `Base subdomain` مثل `vpn`
- `Cloudflare API token`

بعد پروژه این اطلاعات را در config نگه می‌دارد و token را به‌صورت رمز‌شده در دیتابیس ذخیره می‌کند.

### بعد از آن هنگام افزودن سرور چه می‌شود؟
وقتی از داخل بات سرور جدید را اضافه می‌کنی:
- Agent روی سرور نصب می‌شود
- سرور health check می‌دهد
- Master hostname یا IP مقصد SSH را به IP قابل استفاده برای رکورد DNS تبدیل می‌کند
- Cloudflare API صدا زده می‌شود
- رکورد DNS برای آن سرور ساخته یا به‌روزرسانی می‌شود
- نام DNS نهایی داخل دیتابیس سرور ذخیره می‌شود
- در صورت موفقیت، همان نام DNS می‌تواند به‌عنوان `public_host` سرور استفاده شود

### Cloudflare در این پروژه چه کاری **نمی‌کند**؟
برای جلوگیری از سوءبرداشت، این موارد را پروژه انجام نمی‌دهد:
- Cloudflare Tunnel نمی‌سازد
- WARP نصب نمی‌کند
- گواهی TLS سمت Cloudflare برای Xray مدیریت نمی‌کند
- رکوردهای پیچیده غیر از مدیریت DNS مورد نیاز این پروژه را به‌صورت خودکار نمی‌چیند
- به‌صورت پیش‌فرض رکوردها را **proxied** نمی‌کند؛ خروجی فعلی روی DNS-only است

### اگر Cloudflare روشن باشد، آیا لازم است خودت A record بسازی؟
- برای **سرورهایی که از داخل بات با SSH اضافه می‌کنی**، معمولاً نه؛ چون خود پروژه رکورد را می‌سازد
- برای **دامنه‌ای که خودت به‌صورت دستی برای Local Node وارد می‌کنی**، بهتر است از قبل DNS را درست کرده باشی یا حداقل بدانی کجا قرار است اشاره کند
- برای **subscription_base_url** هم بهتر است آدرس عمومی درست و نهایی را خودت وارد کنی، چون این آدرس همان چیزی است که کاربر دریافت می‌کند

### بهترین الگوی عملی
یک الگوی تمیز این است:
- دامنه اصلی: `example.com`
- base subdomain: `vpn`
- نام سرورها: `ir1`, `ir2`, `de1`

در این حالت خروجی‌ها می‌شوند:
- `ir1.vpn.example.com`
- `ir2.vpn.example.com`
- `de1.vpn.example.com`

این کار هم مدیریت را تمیزتر می‌کند، هم داخل پنل و subscription نام‌ها قابل فهم‌تر می‌مانند.

---

## وضعیت سرویس‌ها بعد از نصب | Services after installation

### روی Master
در Debian/Ubuntu:

```bash
systemctl status sahar-master-bot
systemctl status sahar-master-scheduler
systemctl status sahar-master-subscription
```

اگر Local Node فعال باشد:

```bash
systemctl status sahar-master-local-agent
systemctl status xray
```

در Alpine:

```bash
rc-service sahar-master-bot status
rc-service sahar-master-scheduler status
rc-service sahar-master-subscription status
```

اگر Local Node فعال باشد:

```bash
rc-service sahar-master-local-agent status
rc-service xray status
```

### روی Agent
در Debian/Ubuntu:

```bash
systemctl status sahar-agent
systemctl status xray
```

در Alpine:

```bash
rc-service sahar-agent status
rc-service xray status
```

---

## نکات امنیتی مهم | Security notes

- برای Cloudflare فقط دسترسی‌های لازم را بده:
  - `Zone Read`
  - `DNS Write`
- برای Agent بهتر است `Allowed source IPs/CIDRs` را روی IP مستر تنظیم کنی، نه روی حالت باز
- توکن Agent را طولانی و تصادفی نگه دار
- اگر با SSH provisioning کار می‌کنی، ترجیحاً با root وصل شو یا مطمئن شو sudo آماده است
- اگر از دامنه استفاده می‌کنی، قبل از ادامه نصب مطمئن شو DNS درست resolve می‌شود
- بهتر است `subscription_base_url` را خالی نگذاری و آدرس نهایی عمومی را وارد کنی

---

## حداقل منابع پیشنهادی | Suggested minimum resources

### Master فقط مدیریتی
- 1 vCPU
- 1 GB RAM
- 10 GB SSD

### Master + Local Node
- 2 vCPU
- 2 GB RAM
- 20 GB SSD

### Agent
- 1 vCPU
- 1 GB RAM
- 10 GB SSD

این اعداد توصیه عملی هستند، نه محدودیت سخت کد.

---

## ساختار فایل‌ها | Project tree

```text
install.sh
install_master.sh
install_agent.sh
master_app/
  agent_client.py
  backup_manager.py
  bootstrap_cloudflare.py
  cloudflare_manager.py
  bot.py
  db.py
  error_tools.py
  notifier.py
  provisioner.py
  register_local_server.py
  requirements.txt
  scheduler.py
  subscription_api.py
  utils.py
agent_app/
  agent_api.py
  requirements.txt
  utils.py
  xray_manager.py
assets/
  banner.png
  master-install.png
  agent-install.png
VERSION
LICENSE
README.md
PATCH_NOTES.txt
```

---

## نمای نصب | Installation preview

### نصب Master
<p align="center">
  <img src="assets/master-install.png" alt="Master install" width="85%">
</p>

### نصب Agent
<p align="center">
  <img src="assets/agent-install.png" alt="Agent install" width="85%">
</p>
