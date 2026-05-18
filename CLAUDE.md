# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Django 5.1 backend + server-rendered admin panel for **Área 30 Barber Club** (Restrepo - Meta). Public booking site in Spanish, role-based admin panel, REST API (DRF + SimpleJWT), and a financial back-office (sales, commissions, daily cash close, ROI for partners). Deployed on Railway with PostgreSQL + Cloudinary media + WhiteNoise static

Language of the domain, models, comments, and UI is **Spanish**. Keep new user-facing strings in Spanish; code identifiers can stay English. Currency is COP (stored as `DecimalField(decimal_places=0)`).

## Settings module gotcha (important)

[manage.py](manage.py) defaults `DJANGO_SETTINGS_MODULE` to **`config.settings.production`**, not `development`. The production module is tolerant — it falls back to `sqlite:///bookings.db` when `DATABASE_URL` is unset and turns `DEBUG=True` when local — so most commands "just work" without `DATABASE_URL`. But this means:

- Local SQLite for `manage.py` lives in `bookings.db`, **not** `db.sqlite3`. The latter is what `config.settings.development` uses.
- To force the dev settings (real `db.sqlite3`, permissive CORS): `DJANGO_SETTINGS_MODULE=config.settings.development python manage.py <cmd>`.
- [config/settings/build.py](config/settings/build.py) exists only for the Railway/Docker build phase (`collectstatic`) and uses in-memory SQLite + dummy email so the build doesn't need runtime secrets.

## Common commands

```powershell
# Local dev (uses production settings → bookings.db SQLite)
python manage.py runserver

# Explicit dev settings (uses db.sqlite3, CORS open, DEBUG=True)
$env:DJANGO_SETTINGS_MODULE = "config.settings.development"; python manage.py runserver

python manage.py migrate
python manage.py makemigrations <app>
python manage.py createsuperuser
python manage.py collectstatic --noinput

# Custom management commands
python manage.py createsoporte                 # ensures the "soporte_tecnico" superuser
python manage.py seed_services                 # syncs the 9 canonical services
python manage.py send_post_sale_surveys        # apps/bookings — manual trigger of the survey job
python manage.py fix_frank_history             # apps/cashflow — backfill for Frank's commissions
python manage.py reset_roi                     # apps/roi — wipe ROI snapshots

# Full idempotent seed run on every Railway boot (see Procfile)
python seed.py
```

There is **no test suite**. `apps/*/tests.py` are empty stubs and the `test_*.py` files at the repo root are one-off REPL-style smoke scripts (`test_api.py`, `test_adjust.py`, `test_err.py`, `test_upload.py`) — do not treat them as a regression suite. If you add tests, use Django's `python manage.py test` and write them inside the relevant app.

There is no linter or formatter configured.

## Deploy (Railway)

[railpack.toml](railpack.toml) and [Procfile](Procfile) define the same start command (`railpack.toml` wins on Railway, `Procfile` is the fallback):

```
collectstatic → migrate → python seed.py → gunicorn
```

`seed.py` runs on **every** boot. It is intentionally idempotent and is also the project's self-healing layer:

- Re-creates the canonical 9 services and the two `PaymentMethod`s.
- Re-creates/updates the canonical superusers (`camilorf`, `juandavid.castro`, `soporte_tecnico`) and the operational user `frank`.
- Forces `Partner` rows to exactly the two socios (Camilo + Juan David at 50/50).
- Contains **schema-repair fallbacks** that use `connection.schema_editor()` to add tables/columns (e.g. `bookings_blockeddate`, `cashflow_sale.approval_status`) when a migration silently failed in production. If you add a new field that production-might-be-missing, follow this pattern rather than relying on `migrate` alone — Railway's migration history has been unreliable here in the past.

The URL [/init-soporte/](config/urls.py) is a one-shot web endpoint that runs `createsoporte` + `seed_services` from the browser — used to recover access if a deploy goes sideways.

## Architecture

### Apps and their responsibilities

All apps live under [apps/](apps/) and are registered as `apps.<name>` in [INSTALLED_APPS](config/settings/base.py).

| App | Owns | Key models |
| --- | --- | --- |
| [users](apps/users/) | Auth, roles, the barbershop entity, **all admin panel HTML views** | `Barbershop`, `UserProfile` |
| [services](apps/services/) | The 9 canonical service offerings | `Service` |
| [barbers](apps/barbers/) | Barber profiles, weekly schedules, gallery, reels | `Barber`, `BarberUnavailability`, `GalleryImage`, `Reel` |
| [bookings](apps/bookings/) | Reservations, reviews, blocked dates, suggestions, **email + scheduler** | `Booking`, `Review`, `BlockedDate`, `Suggestion` |
| [clients](apps/clients/) | Client master data (derived from bookings) | — |
| [cashflow](apps/cashflow/) | Checkout/sale confirmation, commissions, daily close, expenses, inventory sales | `Sale`, `Commission`, `Expense`, `DailyClose`, `InventorySale`, `PaymentMethod` |
| [inventory](apps/inventory/) | Stock items consumed by services / sold directly | `InventoryItem` |
| [roi](apps/roi/) | Partner investments + monthly ROI snapshots | `Partner`, `PartnerInvestment`, `MonthlyROISnapshot` |
| [analytics](apps/analytics/) | Stats endpoints + `CatchAllExceptionMiddleware` (returns JSON 500s) | — |

### URL layout ([config/urls.py](config/urls.py))

- `/` — public booking site (Spanish, server-rendered templates from [templates/public/](templates/public/)).
- `/barbero/` — barber-self-service pages.
- `/admin-panel/` — staff admin panel (server-rendered, all HTML views live in [apps/users/views.py](apps/users/views.py); templates in [templates/admin/](templates/admin/)). **Not** Django's built-in admin.
- `/admin-panel/roi/` — partner ROI dashboard.
- `/django-admin/` — Django's stock admin, kept as a fallback.
- `/api/` — public API (services, barbers, bookings create).
- `/api/admin/` — staff API, JWT-protected via role permissions.
- `/init-soporte/` — recovery endpoint, see Deploy section.

### Role model (critical for any feature touching the admin/API)

[UserProfile](apps/users/models.py) has four roles with **non-overlapping permission properties**:

```
superadmin         → Camilo, Juan David: prices, promos, fixed expenses, audit, staff mgmt
operational_admin  → Frank: confirm sales, tips, daily close, inventory
admin              → standard shop admin: client master data, basic ops
barber             → own agenda + pre-approved discounts only
```

Permission checks live in two places — always use them, do not reinvent:

1. Granular `@property` methods on `UserProfile` (`can_modify_prices`, `can_confirm_sales`, `can_do_daily_close`, `can_manage_inventory`, …). Use these inside views/templates.
2. DRF permission classes in [apps/users/permissions.py](apps/users/permissions.py): `IsSuperAdmin`, `IsOperationalAdminOrAbove`, `IsAdminOrAbove`, `IsBarberOrAbove`, `HasProfilePermission` (drives off a `required_permission` attr on the view). Use these on `APIView`/`ViewSet`s.

Note the asymmetry: `is_admin` returns True for `admin`, `operational_admin`, and `superadmin`. `is_admin_only` is the one that returns True **just** for plain admin. Don't mix them up.

### Booking integrity

[Booking](apps/bookings/models.py) enforces no-double-booking in two layers — both matter:

1. DB-level `UniqueConstraint(barber, date, time)` filtered to `status IN (pending, confirmed)`.
2. Model `clean()` checks **time-range overlap** using `duration_minutes`, since the unique constraint only catches exact start-time collisions.

If you bypass the constraint (e.g. `update()` instead of `save()`), you also bypass the overlap check. Prefer the serializer path.

Statuses recently changed: manual-service bookings are now created as **`confirmed`** (not `completed`) so they remain manageable. See commit `6770249`.

### Sale / Commission auto-calculation

[Sale.save()](apps/cashflow/models.py) recomputes `final_price = base_price + added_value_amount - discount_amount` and `total_paid = final_price + tip_amount` on every save. [Commission.save()](apps/cashflow/models.py) recomputes `basis_amount` from the parent `Sale` based on `discount_assumed_by` (`company` / `barber` / `shared` / `none`) and applies `percentage` from the barber's profile. **Do not set these computed fields manually** — set the inputs, then save.

### Email + background jobs

- Booking emails ([apps/bookings/emails.py](apps/bookings/emails.py)) use SMTP via `SMTP_*` env vars (prefixed to avoid clashing with Railpack's `EMAIL_*` build secrets — see [base.py](config/settings/base.py)).
- An APScheduler `BackgroundScheduler` is started inside [BookingsConfig.ready()](apps/bookings/apps.py) and runs [send_upcoming_reminders](apps/bookings/scheduler.py) every 15 minutes (sends a reminder ~2 hours before each appointment). It is suppressed in tests via `settings.TESTING` and guarded against Django's dev-server double-start with `RUN_MAIN`. Since it lives in `ready()`, **any process that imports the app starts the scheduler** — keep it idempotent and side-effect-light.

### Media storage

[base.py](config/settings/base.py) wires up Cloudinary as the `default` storage when `CLOUDINARY_CLOUD_NAME` is set; locally and during build it falls back to filesystem (`media/`). [apps/barbers/models.py](apps/barbers/models.py) explicitly uses `RawMediaCloudinaryStorage` for the `Reel.video` field to bypass Pillow's image validation. If you add another video/raw upload, do the same.

## Conventions

- New apps go under `apps/<name>/` and are registered as `apps.<name>`.
- Monetary fields use `DecimalField(max_digits=10-12, decimal_places=0)` — COP has no cents.
- The admin panel is hand-rolled HTML/JS (no SPA framework), not Django's admin. Add new pages by: view in [apps/users/views.py](apps/users/views.py), template in [templates/admin/](templates/admin/), and a JSON endpoint in the relevant app's `urls_admin*.py`.
- Timezone is `America/Bogota` and `USE_TZ=True`; combine date+time with `timezone.make_aware(...)` (see `Booking.can_cancel`).
- Don't write any tests against the in-process scheduler; gate scheduler-touching code on `settings.TESTING`.
