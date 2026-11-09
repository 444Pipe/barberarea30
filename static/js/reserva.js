/* ═══════════════════════════════════════════════════════════════════
   Panel de reserva de Área 30 (nov-2026)

   Reemplaza el asistente de 4 pasos de /booking/. Todo en una pantalla:
   servicio → día (ya viene el primero con cupo) → hora → barbero
   (opcional, "El primero libre") → nombre y WhatsApp → Reservar.

   - Lo abre cualquier enlace a /reservar/ o /booking/ de la página (con
     ?servicio= y ?barbero= opcionales) y la URL ?reservar=1 al cargar.
   - Recuerda al cliente SOLO en su propio navegador (localStorage) para
     ofrecerle "¿Lo de siempre?".
   - Reserva por el mismo POST /api/bookings/ de siempre: el servidor
     vuelve a validar todo y, con barber_id "any", asigna el barbero.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var root = document.getElementById('rsv');
  if (!root) return;

  var WHATSAPP = '573112651032';
  var STORE_KEY = 'a30.cliente';
  var DAYS_AHEAD = 14;
  var DOW = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
  var MON = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

  function $(id) { return document.getElementById(id); }
  var el = {
    sheet: $('rsv-sheet'), head: $('rsv-head'), body: $('rsv-body'),
    again: $('rsv-again'), againName: $('rsv-again-name'), againWhat: $('rsv-again-what'),
    svcBox: $('rsv-svc-box'), days: $('rsv-days'), slots: $('rsv-slots'), timeNote: $('rsv-time-note'),
    barbers: $('rsv-barbers'), data: $('rsv-blk-data'),
    name: $('rsv-name'), phone: $('rsv-phone'), more: $('rsv-more'), extra: $('rsv-extra'),
    email: $('rsv-email'), notes: $('rsv-notes'), optin: $('rsv-optin'), forget: $('rsv-forget'),
    err: $('rsv-err'), sumWhat: $('rsv-sum-what'), sumPrice: $('rsv-sum-price'), book: $('rsv-book'),
    done: $('rsv-done')
  };

  var S = {
    services: [], barbers: [], closedDays: {},
    svc: null, svcOpen: true,
    day: null, dayByUser: false, seeking: false,
    time: null, barber: 'any',
    avail: {},            // "svcId|fecha" → { status, times: {hora: [ids libres]}, listed: [horas] }
    sending: false, pushed: false, opener: null, againDismissed: false
  };

  // ─── Utilidades ───────────────────────────────────────────────
  function pad(n) { return String(n).padStart(2, '0'); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function bogotaNow() { return new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Bogota' })); }
  function ymd(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
  function parseYmd(s) { var p = s.split('-').map(Number); return new Date(p[0], p[1] - 1, p[2]); }
  function money(n) { return '$' + Math.round(Number(n)).toLocaleString('es-CO'); }
  function hm(t) { var p = t.split(':').map(Number); return { h: p[0], m: p[1] }; }
  function hourLabel(t) { var x = hm(t); return (x.h % 12 || 12) + ':' + pad(x.m) + (x.h >= 12 ? ' p. m.' : ' a. m.'); }
  function hourShort(t) { var x = hm(t); return (x.h % 12 || 12) + ':' + pad(x.m); }
  function firstName(n) { return String(n || '').trim().split(/\s+/)[0] || ''; }
  // Slug del asistente viejo (enlaces /booking/#gold-exclusive) y uno limpio sin tildes
  function legacySlug(s) { return String(s).toLowerCase().replace(/[\s\W-]+/g, '-'); }
  function niceSlug(s) {
    return String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }
  function phoneDigits() { return el.phone.value.replace(/\D/g, ''); }

  function dayList() {
    var t = bogotaNow(); t.setHours(0, 0, 0, 0);
    var out = [];
    for (var i = 0; i < DAYS_AHEAD; i++) {
      var d = new Date(t); d.setDate(t.getDate() + i);
      var date = ymd(d);
      out.push({
        date: date,
        label: i === 0 ? 'Hoy' : i === 1 ? 'Mañana' : DOW[d.getDay()],
        sub: d.getDate() + ' ' + MON[d.getMonth()],
        closed: !!S.closedDays[date]
      });
    }
    return out;
  }
  function dayIndex(date) {
    var l = dayList();
    for (var i = 0; i < l.length; i++) if (l[i].date === date) return i;
    return -1;
  }
  function dayShort(date) {
    var i = dayIndex(date), d = parseYmd(date);
    if (i === 0) return 'Hoy';
    if (i === 1) return 'Mañana';
    return DOW[d.getDay()] + ' ' + d.getDate() + ' ' + MON[d.getMonth()];
  }
  function dayLong(date) {
    var s = parseYmd(date).toLocaleDateString('es-CO', { weekday: 'long', day: 'numeric', month: 'long' });
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // ─── Memoria del cliente (solo en su navegador) ───────────────
  function recall() { try { return JSON.parse(localStorage.getItem(STORE_KEY) || 'null'); } catch (e) { return null; } }
  function remember(rec) { try { localStorage.setItem(STORE_KEY, JSON.stringify(rec)); } catch (e) { /* modo privado */ } }
  function forget() { try { localStorage.removeItem(STORE_KEY); } catch (e) { /* nada */ } }

  // ─── Datos ────────────────────────────────────────────────────
  var dataPromise = null;
  function getJSON(url) {
    return fetch(url, { headers: { Accept: 'application/json' } }).then(function (r) {
      if (!r.ok) throw new Error(url + ' ' + r.status);
      return r.json();
    });
  }
  function loadData() {
    if (dataPromise) return dataPromise;
    dataPromise = Promise.all([
      getJSON('/api/servicios-nativos/'),
      getJSON('/api/barberos-nativos/').catch(function () { return { barberos: [] }; }),
      getJSON('/api/blocked-dates/').catch(function () { return []; })
    ]).then(function (res) {
      S.services = (res[0].servicios || []).map(function (s) { s.price = Number(s.price); return s; });
      S.barbers = res[1].barberos || [];
      S.closedDays = {};
      (Array.isArray(res[2]) ? res[2] : []).forEach(function (b) {
        if (!b.start_time) S.closedDays[b.date] = true;   // con horario = día recortado, no cerrado
      });
    }).catch(function (err) { dataPromise = null; throw err; });
    return dataPromise;
  }

  function barbersFor(svc) {
    if (svc && svc.exclusive_barber_id) {
      return S.barbers.filter(function (b) { return b.id === svc.exclusive_barber_id; });
    }
    return S.barbers;
  }
  function barberById(id) {
    for (var i = 0; i < S.barbers.length; i++) if (S.barbers[i].id === id) return S.barbers[i];
    return null;
  }

  function availKey(svc, date) { return svc.id + '|' + date; }
  function loadDay(svc, date) {
    var key = availKey(svc, date);
    if (S.avail[key]) return S.avail[key].promise;
    var entry = { status: 'loading', times: {}, listed: [] };
    S.avail[key] = entry;
    if (S.closedDays[date]) {
      entry.status = 'ok';
      entry.promise = Promise.resolve(entry);
      return entry.promise;
    }
    var list = barbersFor(svc);
    entry.promise = Promise.allSettled(list.map(function (b) {
      return getJSON('/api/barbers/' + b.id + '/availability/?date=' + date + '&service_id=' + svc.id)
        .then(function (a) { return { b: b, a: a }; });
    })).then(function (results) {
      var anyOk = false, seen = {};
      results.forEach(function (res) {
        if (res.status !== 'fulfilled') return;
        anyOk = true;
        var b = res.value.b, a = res.value.a;
        if (a.day_off) return;
        (a.slots || []).forEach(function (slot) {
          if (!seen[slot.time]) { seen[slot.time] = true; entry.listed.push(slot.time); }
          if (slot.available) (entry.times[slot.time] = entry.times[slot.time] || []).push(b.id);
        });
      });
      entry.listed.sort();
      entry.status = (anyOk || !list.length) ? 'ok' : 'error';
      if (entry.status === 'error') delete S.avail[key];   // se puede reintentar
      return entry;
    });
    return entry.promise;
  }

  function isPast(date, t) {
    var now = bogotaNow();
    if (date !== ymd(now)) return false;
    var x = hm(t);
    return x.h * 60 + x.m <= now.getHours() * 60 + now.getMinutes();
  }
  function slotFree(entry, date, t) {
    if (isPast(date, t)) return false;
    var ids = entry.times[t] || [];
    return S.barber === 'any' ? ids.length > 0 : ids.indexOf(S.barber) !== -1;
  }
  function hasFree(entry, date) {
    for (var i = 0; i < entry.listed.length; i++) if (slotFree(entry, date, entry.listed[i])) return true;
    return false;
  }
  function currentEntry() { return S.svc && S.day ? S.avail[availKey(S.svc, S.day)] : null; }

  // El día viene marcado en el primero con cupo: se busca desde `from`.
  var seekToken = 0;
  function seekFirstFreeDay(from) {
    var token = ++seekToken, svc = S.svc, days = dayList();
    S.seeking = true; S.time = null; S.dayByUser = false;
    render();
    var i = Math.max(0, from || 0);
    function next() {
      if (token !== seekToken || S.svc !== svc) return;
      while (i < days.length && days[i].closed) i++;
      if (i >= days.length) {
        S.seeking = false; S.day = days[Math.max(0, from || 0)].date; render(); return;
      }
      var date = days[i].date;
      loadDay(svc, date).then(function (entry) {
        if (token !== seekToken || S.svc !== svc) return;
        if (entry.status === 'ok' && hasFree(entry, date)) {
          S.seeking = false; S.day = date; render(); scrollDayIntoView(); return;
        }
        i++; next();
      });
    }
    next();
  }
  function scrollDayIntoView() {
    var chip = el.days.querySelector('[aria-pressed="true"]');
    if (chip) el.days.scrollLeft = Math.max(0, chip.offsetLeft - el.days.offsetLeft - 12);
  }

  // ─── Pintar ───────────────────────────────────────────────────
  function render() {
    renderAgain(); renderServices(); renderDays(); renderSlots(); renderBarbers(); renderSummary();
  }

  function againService(r) {
    if (!r || !r.svcId || S.againDismissed || S.svc) return null;
    for (var i = 0; i < S.services.length; i++) {
      var s = S.services[i];
      if (s.id === r.svcId && !s.requires_consultation) return s;
    }
    return null;
  }
  function renderAgain() {
    var r = recall(), svc = againService(r);
    el.again.hidden = !svc;
    if (!svc) return;
    var b = r.barberId !== 'any' ? barberById(r.barberId) : null;
    el.againName.textContent = firstName(r.name);
    el.againWhat.textContent = svc.name + (b ? ' con ' + b.nombre : '');
  }

  function renderServices() {
    if (!S.services.length) return;
    if (S.svc && !S.svcOpen) {
      el.svcBox.innerHTML =
        '<div class="rsv-picked"><div><b>' + esc(S.svc.name) + '</b><small>' + money(S.svc.price) +
        ' · ' + S.svc.duration_minutes + ' min</small></div>' +
        '<button type="button" class="rsv-link" data-act="svc-change">Cambiar</button></div>';
      return;
    }
    var anyConsult = false;
    var cards = S.services.map(function (s) {
      var c = !!s.requires_consultation; if (c) anyConsult = true;
      return '<button type="button" class="rsv-svc' + (c ? ' is-consult' : '') + '" data-svc="' + s.id +
        '" aria-pressed="' + !!(S.svc && S.svc.id === s.id) + '"><b>' + esc(s.name) + '</b><small>' +
        (c ? 'A consulta · WhatsApp' : money(s.price) + ' · ' + s.duration_minutes + ' min') + '</small></button>';
    }).join('');
    el.svcBox.innerHTML = '<div class="rsv-svcs" role="group" aria-label="Servicios">' + cards + '</div>' +
      (anyConsult ? '<p class="rsv-hint">Los servicios a consulta se agendan por WhatsApp.</p>' : '');
  }

  function renderDays() {
    el.days.innerHTML = dayList().map(function (d) {
      return '<button type="button" class="rsv-chip rsv-day" data-day="' + d.date + '" aria-pressed="' +
        (S.day === d.date && !S.seeking) + '"' + (d.closed ? ' disabled' : '') + '>' + d.label +
        '<small>' + (d.closed ? 'Cerrado' : d.sub) + '</small></button>';
    }).join('');
  }

  function loadingHtml(text) {
    return '<p class="rsv-loading"><span class="rsv-spin" aria-hidden="true"></span>' + text + '</p>';
  }
  function renderSlots() {
    el.timeNote.textContent = '';
    if (!S.svc) {
      el.slots.innerHTML = '<p class="rsv-empty">Elige un servicio para ver las horas libres.</p>';
      return;
    }
    if (S.seeking || !S.day) { el.slots.innerHTML = loadingHtml('Buscando el primer día con horas libres…'); return; }
    var entry = currentEntry();
    if (!entry || entry.status === 'loading') { el.slots.innerHTML = loadingHtml('Consultando las horas…'); return; }
    var times = entry.listed.filter(function (t) { return !isPast(S.day, t); });
    var free = times.filter(function (t) { return slotFree(entry, S.day, t); });
    if (!free.length) {
      var b = S.barber !== 'any' ? barberById(S.barber) : null;
      var who = b ? ' con ' + esc(b.nombre) : '';
      var closed = S.closedDays[S.day];
      el.slots.innerHTML = '<p class="rsv-empty">' +
        (closed ? 'Este día el club está cerrado.' : 'No quedan horas libres' + who + ' este día.') +
        ' <button type="button" class="rsv-link" data-act="next-day">Ver el siguiente día con cupo</button></p>';
      return;
    }
    var groups = [
      ['Mañana', function (t) { return hm(t).h < 12; }],
      ['Tarde', function (t) { var h = hm(t).h; return h >= 12 && h < 18; }],
      ['Noche', function (t) { return hm(t).h >= 18; }]
    ];
    var html = '';
    groups.forEach(function (g) {
      var ts = times.filter(g[1]);
      if (!ts.length) return;
      html += '<p class="rsv-group">' + g[0] + '</p>';
      ts.forEach(function (t) {
        var ok = slotFree(entry, S.day, t);
        html += '<button type="button" class="rsv-slot" data-time="' + t + '" aria-pressed="' + (S.time === t) +
          '" aria-label="' + hourLabel(t) + (ok ? '' : ', ocupada') + '"' + (ok ? '' : ' disabled') + '>' +
          hourShort(t) + '</button>';
      });
    });
    el.slots.innerHTML = html;
    if (free.length < times.length) el.timeNote.textContent = 'Tachadas: ya ocupadas';
  }

  function renderBarbers() {
    var list = barbersFor(S.svc), entry = currentEntry();
    var freeAt = (S.time && entry && entry.times[S.time]) || null;
    var html = '<button type="button" class="rsv-chip rsv-barber" data-barber="any" aria-pressed="' +
      (S.barber === 'any') + '"><span class="rsv-ava" aria-hidden="true">★</span>El primero libre</button>';
    list.forEach(function (b) {
      var busy = !!(freeAt && freeAt.indexOf(b.id) === -1);
      var ava = b.avatar ? '<img src="' + esc(b.avatar) + '" alt="" loading="lazy">' : esc(String(b.nombre || '?').charAt(0));
      html += '<button type="button" class="rsv-chip rsv-barber" data-barber="' + b.id + '" aria-pressed="' +
        (S.barber === b.id) + '"' + (busy ? ' disabled' : '') + '><span class="rsv-ava" aria-hidden="true">' + ava +
        '</span><span>' + esc(b.nombre) + (busy ? '<small>Ocupado a esa hora</small>' : '') + '</span></button>';
    });
    el.barbers.innerHTML = html;
  }

  function missing() {
    if (!S.svc) return ['svc', 'Elige un servicio'];
    if (S.seeking || !S.day) return ['day', 'Buscando horas…'];
    if (!S.time) return ['time', 'Elige la hora'];
    if (!el.name.value.trim()) return ['name', 'Escribe tu nombre'];
    if (phoneDigits().length < 7) return ['phone', 'Escribe tu WhatsApp'];
    var em = el.email.value.trim();
    if (em && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em)) return ['email', 'Revisa el correo'];
    return null;
  }
  function renderSummary() {
    var parts = [];
    if (S.svc) parts.push(S.svc.name);
    if (S.svc && S.day && !S.seeking) parts.push(dayShort(S.day));
    if (S.time) parts.push(hourLabel(S.time));
    el.sumWhat.textContent = parts.length ? parts.join(' · ') : 'Elige servicio y hora';
    el.sumPrice.textContent = S.svc ? money(S.svc.price) : '';
    var m = missing();
    el.book.textContent = S.sending ? 'Reservando…' : (m ? m[1] : 'Reservar');
    el.book.classList.toggle('is-pending', !!m && !S.sending);
  }

  function showErr(msg) { el.err.textContent = msg; el.err.hidden = false; el.err.scrollIntoView({ block: 'nearest' }); }
  function hideErr() { el.err.hidden = true; el.err.textContent = ''; }

  // ─── Acciones ─────────────────────────────────────────────────
  function openWhatsApp(text) {
    window.open('https://wa.me/' + WHATSAPP + '?text=' + encodeURIComponent(text), '_blank', 'noopener');
  }

  function selectService(svc) {
    if (svc.requires_consultation) {
      openWhatsApp('Hola Área 30 👋\n\nQuiero agendar el servicio *' + svc.name +
        '* (a consulta). ¿Me podrían indicar disponibilidad, precio y condiciones?\n\n¡Gracias!');
      return;
    }
    var changed = !S.svc || S.svc.id !== svc.id;
    S.svc = svc; S.svcOpen = false; S.againDismissed = true;
    if (S.barber !== 'any' && !barbersFor(svc).some(function (b) { return b.id === S.barber; })) S.barber = 'any';
    if (changed) S.time = null;
    if (S.day && S.dayByUser) {
      loadDay(svc, S.day).then(render);
      render();
    } else if (changed || !S.day) {
      seekFirstFreeDay(0);
    } else {
      render();
    }
  }

  function selectDay(date) {
    seekToken++; S.seeking = false;
    S.day = date; S.dayByUser = true; S.time = null;
    if (S.svc) loadDay(S.svc, date).then(render);
    render();
  }

  function selectBarber(v) {
    S.barber = v === 'any' ? 'any' : Number(v);
    var entry = currentEntry();
    if (S.time && entry && !slotFree(entry, S.day, S.time)) S.time = null;
    // Si ese barbero no tiene cupo este día, saltar al siguiente día en que sí.
    if (S.svc && S.day && !S.seeking && entry && entry.status === 'ok' && !hasFree(entry, S.day) && !S.dayByUser) {
      seekFirstFreeDay(Math.max(0, dayIndex(S.day)));
      return;
    }
    render();
  }

  function selectTime(t) {
    S.time = t;
    hideErr();
    render();
    if (!el.name.value.trim() || phoneDigits().length < 7) {
      el.data.scrollIntoView({ behavior: smooth(), block: 'nearest' });
    }
  }

  function smooth() { return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'; }

  function focusMissing(key) {
    var map = { svc: el.svcBox, day: el.days, time: el.slots, name: el.name, phone: el.phone, email: el.email };
    var target = map[key];
    if (!target) return;
    if (key === 'email') { el.extra.hidden = false; el.more.setAttribute('aria-expanded', 'true'); }
    target.scrollIntoView({ behavior: smooth(), block: 'center' });
    if (target.tagName === 'INPUT') {
      target.classList.add('is-bad');
      target.focus({ preventScroll: true });
    }
  }

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }
  function firstError(data) {
    if (!data || typeof data !== 'object') return 'No se pudo reservar. Intenta de nuevo.';
    if (typeof data.error === 'string') return data.error;
    if (typeof data.detail === 'string') return data.detail;
    var errs = data.errors || data;
    for (var k in errs) {
      var v = errs[k];
      if (typeof v === 'string') return v;
      if (Array.isArray(v) && typeof v[0] === 'string') return v[0];
    }
    return 'No se pudo reservar. Intenta de nuevo.';
  }

  function submit() {
    var svc = S.svc, day = S.day, time = S.time;
    var payload = {
      client_name: el.name.value.trim(),
      client_phone: el.phone.value.trim(),
      client_email: el.email.value.trim(),
      notes: el.notes.value.trim(),
      service_id: svc.id,
      barber_id: S.barber === 'any' ? 'any' : S.barber,
      date: day,
      time: time,
      privacy_accepted: true,          // tocar Reservar = aceptar (texto bajo el botón)
      marketing_opt_in: el.optin.checked
    };
    var headers = { 'Content-Type': 'application/json', Accept: 'application/json' };
    var token = csrfToken(); if (token) headers['X-CSRFToken'] = token;

    S.sending = true; el.book.disabled = true; hideErr(); renderSummary();
    fetch('/api/bookings/', { method: 'POST', headers: headers, body: JSON.stringify(payload) })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) { return { ok: r.ok, data: data }; });
      })
      .then(function (res) {
        if (res.ok && (res.data.ok || res.data.id)) {
          remember({
            name: payload.client_name, phone: payload.client_phone, email: payload.client_email,
            svcId: svc.id, barberId: S.barber
          });
          showDone(res.data, payload, svc, day, time);
          return;
        }
        showErr(firstError(res.data));
        // Lo más común: alguien tomó esa hora mientras tanto. Se refrescan las horas.
        delete S.avail[availKey(svc, day)];
        S.time = null;
        loadDay(svc, day).then(render);
        render();
      })
      .catch(function () { showErr('No hay conexión. Revisa tu internet e intenta de nuevo.'); })
      .then(function () { S.sending = false; el.book.disabled = false; renderSummary(); });
  }

  function showDone(data, p, svc, day, time) {
    var who = data.barber_name ? esc(data.barber_name) : '';
    var waText = 'Hola Área 30, tengo una cita de ' + svc.name + ' el ' + dayLong(day).toLowerCase() +
      ' a las ' + hourLabel(time) + ' a nombre de ' + p.client_name + '.';
    el.done.innerHTML =
      '<div class="rsv-check" aria-hidden="true">✓</div>' +
      '<h3>¡Listo, ' + esc(firstName(p.client_name)) + '!</h3>' +
      '<p>Tu cita quedó agendada.</p>' +
      '<dl>' +
        '<div><dt>Servicio</dt><dd>' + esc(svc.name) + '</dd></div>' +
        '<div><dt>Día</dt><dd>' + esc(dayLong(day)) + '</dd></div>' +
        '<div><dt>Hora</dt><dd>' + hourLabel(time) + '</dd></div>' +
        (who ? '<div><dt>Te atiende</dt><dd>' + who + '</dd></div>' : '') +
        '<div><dt>Precio</dt><dd>' + money(svc.price) + '</dd></div>' +
      '</dl>' +
      '<p>' + (p.client_email
        ? 'Te enviamos la confirmación a <b>' + esc(p.client_email) + '</b>.'
        : 'Si necesitas cambiarla o cancelarla, escríbenos por WhatsApp.') + '</p>' +
      '<div class="rsv-done-btns">' +
        '<button type="button" class="rsv-solid" data-act="done">Listo</button>' +
        '<a class="rsv-ghost" href="https://wa.me/' + WHATSAPP + '?text=' + encodeURIComponent(waText) +
        '" target="_blank" rel="noopener">Escribir por WhatsApp</a>' +
      '</div>';
    el.done.hidden = false;
    el.done.scrollTop = 0;
    var btn = el.done.querySelector('[data-act="done"]');
    if (btn) btn.focus({ preventScroll: true });
  }

  function resetAfterBooking() {
    el.done.hidden = true; el.done.innerHTML = '';
    S.svc = null; S.svcOpen = true; S.day = null; S.dayByUser = false; S.time = null;
    S.barber = 'any'; S.againDismissed = false; S.avail = {};
    el.notes.value = ''; el.optin.checked = false;
    hideErr();
  }

  function prefill() {
    var r = recall();
    if (r && !el.name.value && !el.phone.value) {
      el.name.value = r.name || '';
      el.phone.value = r.phone || '';
      if (r.email) el.email.value = r.email;
    }
    el.forget.hidden = !r;
    if (r) el.forget.textContent = 'No soy ' + firstName(r.name);
  }

  // ─── Abrir / cerrar ───────────────────────────────────────────
  function findService(v) {
    if (v == null || v === '') return null;
    v = String(v).toLowerCase();
    for (var i = 0; i < S.services.length; i++) {
      var s = S.services[i];
      if (String(s.id) === v || legacySlug(s.name) === v || niceSlug(s.name) === v) return s;
    }
    return null;
  }
  function applyOpts(o) {
    if (o.barbero) {
      var v = String(o.barbero).toLowerCase();
      var b = S.barbers.filter(function (x) { return String(x.id) === v || niceSlug(x.nombre) === v; })[0];
      if (b) S.barber = b.id;
    }
    var svc = findService(o.servicio);
    if (svc) selectService(svc);
  }

  function isOpen() { return root.classList.contains('is-open'); }

  function open(opts) {
    opts = opts || {};
    if (!isOpen()) {
      S.opener = document.activeElement;
      root.classList.add('is-open');
      root.setAttribute('aria-hidden', 'false');
      document.documentElement.classList.add('rsv-lock');
      // El botón "atrás" del celular cierra el panel en vez de salir de la página.
      try { history.pushState({ rsv: 1 }, ''); S.pushed = true; } catch (e) { S.pushed = false; }
      setTimeout(function () { el.sheet.focus({ preventScroll: true }); }, 60);
    }
    var mm = document.getElementById('mobile-menu');
    if (mm) mm.classList.add('hidden');
    prefill();
    render();
    loadData().then(function () { applyOpts(opts); render(); }).catch(function () {
      el.svcBox.innerHTML = '<p class="rsv-empty">No pudimos cargar los servicios. ' +
        '<button type="button" class="rsv-link" data-act="retry">Intentar de nuevo</button></p>';
    });
  }

  function close(fromHistory) {
    if (!isOpen()) return;
    root.classList.remove('is-open');
    root.setAttribute('aria-hidden', 'true');
    document.documentElement.classList.remove('rsv-lock');
    el.sheet.style.removeProperty('--rsv-drag');
    if (!el.done.hidden) resetAfterBooking();
    if (S.pushed && !fromHistory) { S.pushed = false; history.back(); }
    S.pushed = false;
    if (S.opener && S.opener.focus) S.opener.focus({ preventScroll: true });
  }
  window.addEventListener('popstate', function () { if (isOpen()) { S.pushed = false; close(true); } });

  // ─── Eventos dentro del panel ─────────────────────────────────
  root.addEventListener('click', function (e) {
    var t = e.target.closest('[data-svc],[data-day],[data-time],[data-barber],[data-act],[data-rsv-close]');
    if (!t || t.disabled) return;
    if (t.hasAttribute('data-rsv-close')) { close(); return; }
    if (t.dataset.svc) {
      var id = Number(t.dataset.svc);
      var svc = S.services.filter(function (s) { return s.id === id; })[0];
      if (svc) selectService(svc);
      return;
    }
    if (t.dataset.day) { selectDay(t.dataset.day); return; }
    if (t.dataset.time) { selectTime(t.dataset.time); return; }
    if (t.dataset.barber) { selectBarber(t.dataset.barber); return; }
    switch (t.dataset.act) {
      case 'svc-change': S.svcOpen = true; render(); break;
      case 'next-day': seekFirstFreeDay(Math.max(0, dayIndex(S.day)) + 1); break;
      case 'retry': open({}); break;
      case 'done': close(); break;
    }
  });

  $('rsv-again-yes').addEventListener('click', function () {
    var r = recall(), svc = againService(r);
    if (!svc) return;
    var b = r.barberId !== 'any' ? barberById(r.barberId) : null;
    S.barber = b && barbersFor(svc).indexOf(b) !== -1 ? b.id : 'any';
    selectService(svc);
    el.slots.scrollIntoView({ behavior: smooth(), block: 'nearest' });
  });
  $('rsv-again-no').addEventListener('click', function () { S.againDismissed = true; render(); });

  el.forget.addEventListener('click', function () {
    forget();
    el.name.value = ''; el.phone.value = ''; el.email.value = '';
    S.againDismissed = true;
    prefill(); render();
    el.name.focus();
  });

  el.more.addEventListener('click', function () {
    var show = el.extra.hidden;
    el.extra.hidden = !show;
    el.more.setAttribute('aria-expanded', String(show));
    if (show) el.email.focus();
  });

  [el.name, el.phone, el.email].forEach(function (inp) {
    inp.addEventListener('input', function () { inp.classList.remove('is-bad'); hideErr(); renderSummary(); });
  });

  el.book.addEventListener('click', function () {
    if (S.sending) return;
    var m = missing();
    if (m) { focusMissing(m[0]); return; }
    submit();
  });

  // Teclado: Esc cierra y el foco no se escapa del panel.
  root.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { close(); return; }
    if (e.key !== 'Tab') return;
    var f = Array.prototype.filter.call(
      el.sheet.querySelectorAll('button:not([disabled]), a[href], input, textarea'),
      function (x) { return x.offsetParent !== null; });
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  // Celular: se cierra deslizando hacia abajo desde la manija o el encabezado.
  var drag = null;
  function onDown(e) {
    if (window.matchMedia('(min-width: 768px)').matches || e.target.closest('button')) return;
    drag = { y: e.clientY, dy: 0, id: e.pointerId };
    el.sheet.classList.add('is-dragging');
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (_) { /* nada */ }
  }
  function onMove(e) {
    if (!drag) return;
    drag.dy = Math.max(0, e.clientY - drag.y);
    el.sheet.style.setProperty('--rsv-drag', drag.dy + 'px');
  }
  function onUp() {
    if (!drag) return;
    var dy = drag.dy; drag = null;
    el.sheet.classList.remove('is-dragging');
    if (dy > 110) close(); else el.sheet.style.setProperty('--rsv-drag', '0px');
  }
  [el.head, el.sheet.querySelector('.rsv-grip')].forEach(function (h) {
    if (!h) return;
    h.addEventListener('pointerdown', onDown);
    h.addEventListener('pointermove', onMove);
    h.addEventListener('pointerup', onUp);
    h.addEventListener('pointercancel', onUp);
  });

  // ─── Enlaces de la página que abren el panel ──────────────────
  var RESERVA_PATH = /^\/(reservar|booking)(\/|\.html)?$/;
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest('a[href], [data-reservar]');
    if (!a || root.contains(a)) return;
    var opts;
    if (a.hasAttribute('data-reservar')) {
      opts = { servicio: a.getAttribute('data-servicio'), barbero: a.getAttribute('data-barbero') };
    } else {
      var url;
      try { url = new URL(a.getAttribute('href'), location.href); } catch (_) { return; }
      if (url.origin !== location.origin || !RESERVA_PATH.test(url.pathname)) return;
      opts = {
        servicio: url.searchParams.get('servicio') || (url.hash.length > 1 ? decodeURIComponent(url.hash.slice(1)) : null),
        barbero: url.searchParams.get('barbero')
      };
    }
    e.preventDefault();
    open(opts);
  });

  // ─── Enlace directo: /?reservar=1[&servicio=..][&barbero=..] ──
  var params = new URLSearchParams(location.search);
  if (params.has('reservar')) {
    var initial = {
      servicio: params.get('servicio') || (location.hash.length > 1 ? decodeURIComponent(location.hash.slice(1)) : null),
      barbero: params.get('barbero')
    };
    ['reservar', 'servicio', 'barbero'].forEach(function (k) { params.delete(k); });
    var qs = params.toString();
    try { history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '')); } catch (_) { /* nada */ }
    open(initial);
  }

  // Para abrirlo desde otros scripts: window.A30Reserva.open({ servicio: 3 })
  window.A30Reserva = { open: open, close: close };
})();
