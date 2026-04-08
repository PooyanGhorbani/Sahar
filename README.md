# سحر 0.1.21

![Sahar banner](assets/banner.png)

**سامانه مدیریت Xray / VLESS با معماری Master / Agent و پنل تلگرام**  
**Telegram-first Xray / VLESS management platform with master-agent architecture**

![version](https://img.shields.io/badge/version-0.1.21-8b5cf6)
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
unzip sahar_0.1.21_single_installer.zip && cd sahar_0.1.21_single_installer && sudo sh install.sh
```

برای نصب مستقیم Master:

```bash
unzip sahar_0.1.21_single_installer.zip && cd sahar_0.1.21_single_installer && sudo sh install.sh master
```

برای نصب مستقیم Agent:

```bash
unzip sahar_0.1.21_single_installer.zip && cd sahar_0.1.21_single_installer && sudo sh install.sh agent
```

اگر آرگومان ندهی، installer از خودت می‌پرسد که می‌خواهی Master نصب شود یا Agent.

---


## نصب مستقیم از GitHub با یک خط دستور | One-line direct install from GitHub

آدرس واقعی پروژه:

```text
https://github.com/PooyanGhorbani/Sahar
```

این دستورها قبل از clone شدن، اگر `git` روی سرور نباشد آن را خودکار نصب می‌کنند.

### نصب Master از GitHub

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sh install.sh master'
```

### نصب Agent از GitHub

```bash
sh -c 'set -e; if ! command -v git >/dev/null 2>&1; then if [ -f /etc/alpine-release ]; then apk add --no-cache git bash curl unzip ca-certificates; else apt-get update && apt-get install -y git bash curl unzip ca-certificates; fi; fi; rm -rf /opt/sahar && git clone https://github.com/PooyanGhorbani/Sahar.git /opt/sahar && cd /opt/sahar && sh install.sh agent'
```

### نکته مهم

- دستورها را با کاربر `root` اجرا کن
- اگر `git` نصب نباشد، خود دستور آن را نصب می‌کند
- اگر مسیر `/opt/sahar` را نمی‌خواهی، آن را با مسیر دلخواه خودت عوض کن
- برای آپدیت بعدی هم می‌توانی دوباره همین دستور را اجرا کنی

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
unzip sahar_0.1.21_single_installer.zip && cd sahar_0.1.21_single_installer && sudo sh install.sh master
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

در نسخه فعلی سؤال‌های installer تا حد ممکن کم شده‌اند.

### چیزی که واقعاً لازم است
- `Telegram bot token`

### چیزی که به‌صورت اختیاری پرسیده می‌شود
- آیا روی همین سرور **Local Node** هم نصب شود یا نه
- اگر Local Node فعال باشد: فقط **Public Host** همان نود (IP یا Domain)

### چیزهایی که به‌صورت پیش‌فرض تنظیم می‌شوند
- `scheduler_interval_seconds = 300`
- `agent_timeout_seconds = 15`
- `warn_days_left = 3`
- `warn_usage_percent = 80`
- `backup_interval_hours = 24`
- `backup_retention = 10`
- `subscription_bind_host = 0.0.0.0`
- `subscription_bind_port = 8090`
- Cloudflare در شروع **غیرفعال** است
- Reality به‌صورت پیش‌فرض روی:
  - `serverName = www.cloudflare.com`
  - `dest = www.cloudflare.com:443`

### مدیریت بعد از نصب
اگر `admin_chat_ids` در زمان نصب خالی بماند:
- **اولین کاربری که بات را در تلگرام باز کند، خودکار Owner می‌شود**

بعد از نصب می‌توانی از داخل تلگرام با دستور زیر تنظیمات اصلی را تغییر بدهی:

```text
/settings
```

از داخل تلگرام می‌توانی این موارد را تغییر بدهی:
- Subscription base URL
- Scheduler interval
- Agent timeout
- Warning thresholds
- Backup interval / retention
- Cloudflare enable/domain/subdomain/token


## در نصب Agent چه چیزهایی پرسیده می‌شود؟ | Agent installer prompts

نصب Agent هم ساده‌تر شده است.

### چیزی که لازم است
- `Public host` همان سرور (IP یا Domain)

### چیزهایی که خودکار یا پیش‌فرض تنظیم می‌شوند
- `agent_name` از روی host ساخته می‌شود
- `transport_mode = dual`
- `VLESS Simple port = 443`
- `VLESS Reality port = 8443`
- `Xray API port = 10085`
- `fingerprint = chrome`
- `REALITY serverName = www.cloudflare.com`
- `REALITY dest = www.cloudflare.com:443`
- `agent_token` خودکار ساخته می‌شود
- اگر از طریق SSH نصب کنی، `allowed_sources` تا جای ممکن از IP همان SSH client حدس زده می‌شود

### نکته
اگر خواستی نصب Agent کاملاً بدون سؤال باشد، می‌توانی آن را در حالت `NONINTERACTIVE=1` با environment variable اجرا کنی؛ این مسیر برای نصب خودکار از داخل بات استفاده می‌شود.
