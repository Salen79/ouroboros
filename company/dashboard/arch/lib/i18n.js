// i18n — runtime language switch backed by localStorage.
// Exposes: getLang(), setLang(), t(key), tField(obj, fieldName).
//
// Language change triggers full page reload so every view re-renders
// in the chosen language — simpler and less error-prone than trying
// to hot-swap every DOM string.

const LS_KEY = 'arch-lang';
const DEFAULT_LANG = 'ru';

export function getLang() {
  try { return localStorage.getItem(LS_KEY) || DEFAULT_LANG; }
  catch { return DEFAULT_LANG; }
}

export function setLang(lang) {
  if (lang !== 'ru' && lang !== 'en') lang = DEFAULT_LANG;
  try { localStorage.setItem(LS_KEY, lang); } catch {}
  // Reload preserves #hash so current zoom state survives the switch.
  window.location.reload();
}

/**
 * Given an object with `field` and optional `field_en`, return the value
 * for the current language, falling back to the RU field.
 */
export function tField(obj, fieldName) {
  if (!obj) return '';
  const lang = getLang();
  if (lang === 'en') {
    const ek = fieldName + '_en';
    if (obj[ek] != null) return obj[ek];
  }
  return obj[fieldName] != null ? obj[fieldName] : '';
}

// --- UI strings (things that aren't in architecture.json) ---
const UI = {
  // Top bar + tabs
  'title':                     { ru: 'Архитектура THAI',     en: 'THAI Architecture' },
  'tab.overview':              { ru: 'Обзор',                en: 'Overview' },
  'tab.darkzones':             { ru: 'Тёмные зоны',          en: 'Dark Zones' },
  'tab.memory':                { ru: 'Память',               en: 'Memory' },
  'tab.tools':                 { ru: 'Инструменты',          en: 'Tools' },
  'search.placeholder':        { ru: 'Поиск: файл, инструмент, D-ID…',
                                  en: 'Search: file, tool, D-ID…' },
  'filter.all':                { ru: 'Фильтр: все',          en: 'Filter: all' },
  'filter.write':              { ru: 'Запись',               en: 'Write' },
  'filter.memory':             { ru: 'Только память',        en: 'Memory only' },
  'filter.dark':               { ru: 'Слабости',             en: 'Weaknesses' },
  'filter.tools':              { ru: 'Инструменты',          en: 'Tools' },
  'close':                     { ru: 'Закрыть',              en: 'Close' },
  'loading':                   { ru: 'Загрузка…',            en: 'Loading…' },

  // Overview
  'crumb.overview':            { ru: 'Обзор',                en: 'Overview' },
  'chips.edges.all':           { ru: 'Все связи',            en: 'All edges' },
  'chips.edges.control':       { ru: 'Только управление',    en: 'Control only' },
  'chips.edges.data':          { ru: 'Только данные',        en: 'Data only' },
  'chips.edges.none':          { ru: 'Без связей',           en: 'No edges' },
  'legend.control':            { ru: 'Управление',           en: 'Control' },
  'legend.control.hint':       { ru: 'вызов, контроль',      en: 'invoke, govern' },
  'legend.data':               { ru: 'Данные',               en: 'Data' },
  'legend.data.hint':          { ru: 'чтение, запись, наблюдение',
                                  en: 'read, write, observe' },
  'legend.weaknesses':         { ru: 'Известные слабости',   en: 'Known weaknesses' },

  // Safety pill
  'safety.pill.count':         { ru: n => `⚠ ${n} слабостей`,
                                  en: n => `⚠ ${n} weaknesses` },
  'safety.pill.tooltip':       { ru: n => `${n} известных слабостей — открыть таксономию`,
                                  en: n => `${n} known weaknesses — open taxonomy` },

  // Zoom hint
  'zoom.hint.l0':              { ru: 'клик на орган — увеличить',
                                  en: 'click an organ to zoom in' },
  'zoom.hint.l1':              { ru: 'клик на фон или хлебную крошку — уменьшить',
                                  en: 'click background or breadcrumb to zoom out' },

  // Meta subline
  'meta.tools':                { ru: 'инструментов',         en: 'tools' },
  'meta.weaknesses':           { ru: 'слабостей',            en: 'weaknesses' },
  'meta.modules':              { ru: 'модулей',              en: 'modules' },
  'meta.nodes':                { ru: 'узлов',                en: 'nodes' },
  'meta.edges':                { ru: 'связей',               en: 'edges' },
  'meta.snapshot':             { ru: 'снимок',               en: 'snapshot' },

  // Memory tab
  'memory.title':              { ru: 'Память — по времени жизни',
                                  en: 'Memory — by lifetime' },
  'memory.locations':          { ru: 'хранилищ',             en: 'locations' },
  'memory.subblocks':          { ru: 'под-блока',            en: 'sub-blocks' },

  'mem.working.hint':          { ru: 'Загружается в начале задачи, замещается в конце. Ничего отсюда не переживает рестарт нетронутым.',
                                  en: 'Loaded at task start, replaced at task end. Nothing survives a restart untouched.' },
  'mem.short.hint':             { ru: 'Append-only логи и состояние с TTL. Недавний контекст, регулярно старится.',
                                  en: 'Append-only logs and state with TTL. Recent context, ages out regularly.' },
  'mem.long.hint':              { ru: 'Идентичность, мудрость, навыки, исторические состояния. Пишется редко, читается часто.',
                                  en: 'Identity, wisdom, skills, historical state. Written rarely, read often.' },
  'mem.archive.hint':           { ru: 'Один JSON на задачу. Входные данные для pattern_detector и ретроспективной аналитики.',
                                  en: 'One JSON per task. Input for pattern_detector and retrospective analytics.' },

  // Tools tab kinds (badge)
  'kind.file':                 { ru: 'ФАЙЛ',                 en: 'FILE' },
  'kind.dir':                  { ru: 'ПАПКА',                en: 'DIR' },
  'kind.log':                  { ru: 'ЛОГ',                  en: 'LOG' },
  'kind.json':                 { ru: 'JSON',                 en: 'JSON' },
  'kind.chroma':               { ru: 'CHROMA',               en: 'CHROMA' },
  'kind.virtual':              { ru: 'ВИРТ',                 en: 'VIRT' },
  'kind.virtual.sub':          { ru: 'in-process, не персистится',
                                  en: 'in-process, not persisted' },

  // Dark Zones tab
  'dz.select.hint':            { ru: 'Выберите слабость, чтобы увидеть детали.',
                                  en: 'Pick a weakness to view details.' },
  'dz.empty':                  { ru: 'Ничего не найдено.',   en: 'Nothing found.' },
  'dz.refs.files':             { ru: 'Упомянутые файлы',     en: 'Referenced files' },
  'dz.refs.lines':             { ru: 'Ссылки file:line',     en: 'File:line references' },

  // Panel
  'panel.role':                { ru: 'Роль',                 en: 'Role' },
  'panel.description':         { ru: 'Описание',             en: 'Description' },
  'panel.parameters':          { ru: 'Параметры',            en: 'Parameters' },
  'panel.none':                { ru: 'нет',                  en: 'none' },
  'panel.no_description':      { ru: 'Описание отсутствует', en: 'No description' },
  'panel.writers':             { ru: 'Пишут',                en: 'Writers' },
  'panel.readers':             { ru: 'Читают',               en: 'Readers' },
  'panel.weaknesses':          { ru: 'Известные слабости',   en: 'Known weaknesses' },
  'panel.lines':               { ru: 'строк',                en: 'lines' },
  'panel.layer':               { ru: 'слой',                 en: 'layer' },
  'panel.kind':                { ru: 'тип',                  en: 'kind' },
  'panel.timeout':             { ru: 'таймаут',              en: 'timeout' },
  'panel.seconds':             { ru: 'сек',                  en: 's' },

  // Tools tab filter chips (phase 1 legacy)
  'tools.chip.all':            { ru: 'Все',                  en: 'All' },
  'tools.chip.core':           { ru: 'Core',                 en: 'Core' },
  'tools.chip.write':          { ru: 'Write',                en: 'Write' },
  'tools.chip.destructive':    { ru: 'Опасные',              en: 'Destructive' },
  'tools.chip.consciousness':  { ru: 'Whitelist сознания',   en: 'Consciousness whitelist' },
  'tools.empty':               { ru: q => `Ничего не найдено по запросу ${q}`,
                                  en: q => `Nothing found for ${q}` },
  'tools.total':               { ru: n => `${n} инструментов`,
                                  en: n => `${n} tools` },

  // Lang toggle
  'lang.toggle.title':         { ru: 'Сменить язык интерфейса',
                                  en: 'Switch UI language' },
  'lang.ru.label':             { ru: 'RU',                   en: 'RU' },
  'lang.en.label':             { ru: 'EN',                   en: 'EN' },
};

/**
 * Translate a static UI key. Supports ru/en; if the value is a function,
 * pass additional args through (for pluralization / interpolation).
 */
export function t(key, ...args) {
  const entry = UI[key];
  if (!entry) return key; // fallback — the key itself is a readable hint
  const lang = getLang();
  const val = entry[lang] != null ? entry[lang] : entry.ru;
  return typeof val === 'function' ? val(...args) : val;
}
