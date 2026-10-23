// Читалка: открывает книгу через foliate-js и общается с Python-частью
// через консоль с меткой (туда) и window.reader (оттуда).
import './foliate/view.js'

const $ = s => document.querySelector(s)
const post = msg => console.log('\u2063LITREADER:' + JSON.stringify(msg))

const THEMES = {
    light: { bg: '#ffffff', fg: '#1b1b1b', link: '#1a5fb4' },
    sepia: { bg: '#f4ecd8', fg: '#4b3a2a', link: '#8a4b08' },
    dark:  { bg: '#1e1e1e', fg: '#dadada', link: '#78aeed' },
    black: { bg: '#000000', fg: '#c4c4c4', link: '#78aeed' },
}

const FONTS = {
    book: null,
    serif: 'Georgia, "Noto Serif", "PT Serif", serif',
    sans: '"Inter Variable", Inter, "Noto Sans", sans-serif',
}

let view = null
let settings = null

const bookCSS = s => {
    const t = THEMES[s.theme] ?? THEMES.light
    const font = FONTS[s.font]
    return `
    html {
        color-scheme: ${s.theme === 'light' || s.theme === 'sepia' ? 'light' : 'dark'};
        font-size: ${s.fontSize}px !important;
        background: ${t.bg} !important;
        color: ${t.fg} !important;
    }
    body {
        background: transparent !important;
        color: inherit !important;
    }
    ${font ? `body, body * { font-family: ${font} !important; }` : ''}
    a:link, a:visited { color: ${t.link} !important; }
    p, li, blockquote, dd {
        line-height: ${s.lineHeight} !important;
        text-align: ${s.justify ? 'justify' : 'start'};
        -webkit-hyphens: ${s.hyphenate ? 'auto' : 'manual'};
        hyphens: ${s.hyphenate ? 'auto' : 'manual'};
        -webkit-hyphenate-limit-before: 3;
        -webkit-hyphenate-limit-after: 2;
        -webkit-hyphenate-limit-lines: 2;
        widows: 2;
        orphans: 2;
    }
    [align="left"] { text-align: left; }
    [align="right"] { text-align: right; }
    [align="center"] { text-align: center; }
    pre { white-space: pre-wrap !important; }
    img, svg { max-width: 100%; height: auto; }
    ::highlight(tts) { background-color: rgba(255, 140, 0, 0.38); }
    `
}

const applySettings = s => {
    settings = s
    restyleHighlights()
    const t = THEMES[s.theme] ?? THEMES.light
    document.documentElement.style.setProperty('--bg', t.bg)
    document.documentElement.style.setProperty('--fg', t.fg)
    const r = view?.renderer
    if (!r) return
    r.setAttribute('gap', `${s.margin}%`)
    r.setAttribute('margin', '36px')
    r.setAttribute('max-inline-size', `${s.lineWidth}px`)
    r.setAttribute('max-column-count', s.twoColumns ? '2' : '1')
    r.setStyles?.(bookCSS(s))
}

// Название и автор могут быть строкой, объектом {язык: строка} или массивом
const formatName = x => {
    if (!x) return ''
    if (typeof x === 'string') return x
    if (Array.isArray(x)) return x.map(formatName).filter(Boolean).join(', ')
    if (x.name) return formatName(x.name)
    return Object.values(x)[0] ?? ''
}

const flattenTOC = (items, depth = 0, out = []) => {
    for (const item of items ?? []) {
        out.push({ label: (item.label ?? '').trim(), href: item.href, depth })
        flattenTOC(item.subitems, depth + 1, out)
    }
    return out
}

// --- выделения: цвет — смысл (важное, совет, понятие, вопрос). Рисуем через CSS Custom Highlight API —
// одинаково в EPUB/FB2/MOBI и в PDF (у foliate для PDF нет слоя рисования).
const HL_COLORS = { important: '255,196,0', advice: '76,190,80', concept: '66,145,255', question: '240,98,170' }
let highlights = []                      // [{id, section, cfi, text, prefix, suffix, color, note}]
const hlRanges = new Map()               // id → {range, doc} в загруженных разделах

const hlCSS = () => {
    const dark = settings && !(settings.theme === 'light' || settings.theme === 'sepia')
    const a = dark ? 0.34 : 0.42
    return Object.entries(HL_COLORS).map(([k, c]) => `::highlight(mh-${k}) { background-color: rgba(${c}, ${a}); }`)
        .join('\n') + '\n::highlight(mh-flash) { background-color: rgba(255, 140, 0, 0.7); }'
}
const styleDoc = doc => {
    let el = doc.getElementById('mh-hl-style')
    if (!el) {
        el = doc.createElement('style')
        el.id = 'mh-hl-style'
        ;(doc.head ?? doc.documentElement).append(el)
    }
    el.textContent = hlCSS()
}
// Номер раздела документа: в PDF (фиксированная вёрстка) getContents() его не отдаёт — запоминаем при загрузке
const docIndex = new WeakMap()
const loadedDocs = () => (view?.renderer?.getContents?.() ?? [])
    .map(c => ({ ...c, index: c.index ?? (c.doc ? docIndex.get(c.doc) : undefined) }))
function restyleHighlights() { for (const { doc } of loadedDocs()) if (doc) styleDoc(doc) }

// Текст документа без пробелов с картой «символ → (узел, смещение)»: так цитата находится и в PDF,
// где текстовый слой расставляет пробелы и переносы по-своему
const compact = s => (s ?? '').replace(/\s+/g, '')
const textIndex = doc => {
    const chars = [], map = []
    const walker = doc.createTreeWalker(doc.body ?? doc.documentElement, NodeFilter.SHOW_TEXT)
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const v = n.nodeValue
        for (let i = 0; i < v.length; i++) if (!/\s/.test(v[i])) { chars.push(v[i]); map.push([n, i]) }
    }
    return { text: chars.join(''), map }
}
const findQuote = (doc, h) => {
    const { text, map } = textIndex(doc)
    const q = compact(h.text)
    if (!q) return null
    const pre = compact(h.prefix), suf = compact(h.suffix)
    let at = text.indexOf(pre + q + suf)
    if (at >= 0) at += pre.length
    else {
        at = text.indexOf(q + suf)
        if (at < 0) { at = text.indexOf(pre + q); if (at >= 0) at += pre.length }
        if (at < 0) at = text.indexOf(q)
    }
    if (at < 0) return null
    const [sn, so] = map[at], [en, eo] = map[at + q.length - 1]
    const range = doc.createRange()
    range.setStart(sn, so)
    range.setEnd(en, eo + 1)
    return range
}
const resolveRange = async (doc, index, h) => {
    if (h.cfi) {
        try {
            const { index: i, anchor } = await view.resolveNavigation(h.cfi)
            if (i === index) {
                const r = anchor(doc)
                if (r && compact(r.toString()) === compact(h.text)) return r
            }
        } catch (_) {}
    }
    return findQuote(doc, h)
}
const paintDoc = async (doc, index, attempt = 0) => {
    if (!doc?.defaultView?.CSS?.highlights) return
    styleDoc(doc)
    const byColor = {}
    for (const [id, x] of hlRanges) if (x.doc === doc) hlRanges.delete(id)
    for (const h of highlights) {
        if (h.section !== index) continue
        const range = await resolveRange(doc, index, h)
        if (!range) continue
        hlRanges.set(h.id, { range, doc })
        ;(byColor[h.color] ??= []).push(range)
    }
    const win = doc.defaultView
    for (const k of Object.keys(HL_COLORS)) {
        if (byColor[k]) win.CSS.highlights.set(`mh-${k}`, new win.Highlight(...byColor[k]))
        else win.CSS.highlights.delete(`mh-${k}`)
    }
    // PDF: текстовый слой pdf.js строится уже после загрузки страницы — не нашли всё, пробуем ещё раз
    const want = highlights.filter(h => h.section === index).length
    const got = [...hlRanges.values()].filter(x => x.doc === doc).length
    if (got < want && attempt < 8) setTimeout(() => paintDoc(doc, index, attempt + 1), 400)
}
const setHighlights = async list => {
    highlights = list ?? []
    for (const { doc, index } of loadedDocs()) if (doc) await paintDoc(doc, index)
}

// Панель над выделенным текстом
const bar = document.createElement('div')
bar.id = 'hl-bar'
let barSel = null                        // {doc, index, range}
const hideBar = () => { bar.classList.remove('shown'); barSel = null }
const buildBar = () => {
    bar.replaceChildren()
    for (const [k, c] of Object.entries(HL_COLORS)) {
        const d = document.createElement('div')
        d.className = 'dot'
        d.style.background = `rgb(${c})`
        d.title = T(HL_NAMES[k])
        d.addEventListener('mousedown', e => { e.preventDefault(); addHighlight(k, false) })
        bar.append(d)
    }
    const sep = document.createElement('div')
    sep.className = 'sep'
    bar.append(sep)
    for (const [label, fn] of [[T('Заметка'), () => addHighlight('important', true)],
                               [T('Копировать'), copySelection]]) {
        const b = document.createElement('div')
        b.className = 'act'
        b.textContent = label
        b.addEventListener('mousedown', e => { e.preventDefault(); fn() })
        bar.append(b)
    }
}
const HL_NAMES = { important: 'Важное', advice: 'Совет', concept: 'Понятие', question: 'Вопрос' }
document.body.append(bar)

const frameOffset = doc => {
    const frame = doc.defaultView.frameElement
    const r = frame ? frame.getBoundingClientRect() : { left: 0, top: 0 }
    return { x: r.left, y: r.top }
}
const showBar = (doc, index, range) => {
    const rects = [...range.getClientRects()]
    if (!rects.length) return hideBar()
    if (!bar.childElementCount) buildBar()
    const off = frameOffset(doc)
    const top = Math.min(...rects.map(r => r.top)) + off.y
    const left = (Math.min(...rects.map(r => r.left)) + Math.max(...rects.map(r => r.right))) / 2 + off.x
    barSel = { doc, index, range: range.cloneRange() }
    bar.classList.add('shown')
    const w = bar.offsetWidth, hgt = bar.offsetHeight
    const y = top - hgt - 10 < 4 ? Math.max(...rects.map(r => r.bottom)) + off.y + 10 : top - hgt - 10
    bar.style.left = `${Math.max(6, Math.min(window.innerWidth - w - 6, left - w / 2))}px`
    bar.style.top = `${y}px`
}
const onSelectionChange = (doc, index) => {
    clearTimeout(onSelectionChange.t)
    onSelectionChange.t = setTimeout(() => {
        const sel = doc.getSelection()
        if (!sel || sel.isCollapsed || !sel.rangeCount || !sel.toString().trim()) return hideBar()
        showBar(doc, index, sel.getRangeAt(0))
    }, 250)
}
const around = (doc, range) => {
    const body = doc.body ?? doc.documentElement
    const before = doc.createRange(), after = doc.createRange()
    before.setStart(body, 0)
    before.setEnd(range.startContainer, range.startOffset)
    after.setStart(range.endContainer, range.endOffset)
    after.setEnd(body, body.childNodes.length)
    return { prefix: before.toString().slice(-32), suffix: after.toString().slice(0, 32) }
}
const addHighlight = (color, withNote) => {
    if (!barSel) return
    const { doc, index, range } = barSel
    const text = range.toString().trim()
    let cfi = null
    try { cfi = view.getCFI(index, range) } catch (_) {}
    const loc = view.lastLocation ?? {}
    post({ type: 'highlight-add', section: index, cfi, text, ...around(doc, range), color, withNote,
        chapter: loc.tocItem?.label?.trim() ?? '', fraction: loc.fraction ?? 0 })
    doc.getSelection()?.removeAllRanges()
    hideBar()
}
const copySelection = () => {
    if (!barSel) return
    post({ type: 'copy', text: barSel.range.toString() })
    barSel.doc.getSelection()?.removeAllRanges()
    hideBar()
}

// Клик по выделению — меню (цвет, заметка, удалить); проверяем до перелистывания
const highlightAt = (doc, e) => {
    for (const [id, { range, doc: d }] of hlRanges) {
        if (d !== doc) continue
        for (const r of range.getClientRects())
            if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) return id
    }
    return null
}

const flash = range => {
    try {
        const win = range.startContainer.ownerDocument.defaultView
        win.CSS.highlights.set('mh-flash', new win.Highlight(range))
        setTimeout(() => win.CSS.highlights.delete('mh-flash'), 1600)
    } catch (_) {}
}
const goToHighlight = async id => {
    const h = highlights.find(x => x.id === id)
    if (!h || !view) return false
    if (!hlRanges.has(id)) {
        try {
            if (h.cfi) await view.goTo(h.cfi)
            else await view.renderer.goTo({ index: h.section })
        } catch (_) { await view.renderer.goTo({ index: h.section }) }
        for (const { doc, index } of loadedDocs()) if (doc && index === h.section) await paintDoc(doc, index)
    }
    const x = hlRanges.get(id)
    if (!x) return false
    view.renderer.scrollToAnchor?.(x.range, true)
    flash(x.range)
    return true
}

const onKey = e => {
    const k = e.key
    if (k === 'ArrowLeft' || k === 'PageUp' || k === 'h') view?.goLeft()
    else if (k === 'ArrowRight' || k === 'PageDown' || k === ' ' || k === 'l') view?.goRight()
    else if (k === 'Home') view?.goToFraction(0)
    else if (k === 'Escape') post({ type: 'escape' })
    else return
    e.preventDefault()
}

// Касание: левая треть — назад, правая — вперёд, середина — показать/скрыть панели
const onClick = (doc, e) => {
    if (e.defaultPrevented || e.button !== 0) return
    if (e.target.closest?.('a[href]')) return
    const sel = doc.getSelection()
    if (sel && !sel.isCollapsed) return
    const hit = highlightAt(doc, e)
    if (hit) { post({ type: 'highlight-menu', id: hit }); return }
    const frame = doc.defaultView.frameElement
    const x = (frame ? frame.getBoundingClientRect().left : 0) + e.clientX
    const w = window.innerWidth
    if (x < w * 0.3) view.goLeft()
    else if (x > w * 0.7) view.goRight()
    else post({ type: 'toggle-ui' })
}

// --- жесты: смахивание вверх — оглавление, вниз — панели, щипок / Ctrl+колесо — размер шрифта
const gesture = { start: null, pinch: null, last: null }
const fingers = t => Math.hypot(t[0].screenX - t[1].screenX, t[0].screenY - t[1].screenY)
const attachGestures = target => {
    target.addEventListener('touchstart', e => {
        if (e.touches.length === 2) {
            gesture.pinch = fingers(e.touches)
            gesture.last = null
            gesture.start = null
        } else if (e.touches.length === 1 && !gesture.pinch) {
            const t = e.touches[0]
            gesture.start = { x: t.screenX, y: t.screenY, time: e.timeStamp }
        }
    }, { passive: true })
    target.addEventListener('touchmove', e => {
        if (e.touches.length === 2 && gesture.pinch) {
            e.preventDefault()
            gesture.last = fingers(e.touches)
        }
    }, { passive: false })
    target.addEventListener('touchend', e => {
        if (gesture.pinch) {
            if (e.touches.length === 0) {
                const ratio = gesture.last ? gesture.last / gesture.pinch : 1
                if (ratio > 1.12 || ratio < 0.89) post({ type: 'pinch', scale: ratio })
                gesture.pinch = gesture.last = null
            }
            return
        }
        const st = gesture.start
        gesture.start = null
        if (!st || e.changedTouches.length !== 1) return
        const t = e.changedTouches[0]
        const dx = t.screenX - st.x, dy = t.screenY - st.y
        if (Math.abs(dx) > 70 || e.timeStamp - st.time > 900) return
        if (dy < -110) post({ type: 'swipe-up' })
        else if (dy > 110) post({ type: 'swipe-down' })
    }, { passive: true })
    target.addEventListener('wheel', e => {
        if (!e.ctrlKey) return
        e.preventDefault()
        post({ type: 'pinch', scale: e.deltaY < 0 ? 1.15 : 0.87 })
    }, { passive: false })
}

// --- чтение вслух: текст предложениями с метками, подсветка читаемого
const ttsHighlight = range => {
    view.renderer.scrollToAnchor?.(range, true)
    try {
        const win = range.startContainer.ownerDocument.defaultView
        win.CSS.highlights.set('tts', new win.Highlight(range))
    } catch (_) {}
}
const ttsClear = () => {
    for (const { doc } of view?.renderer?.getContents?.() ?? [])
        try { doc.defaultView.CSS.highlights.delete('tts') } catch (_) {}
}
// SSML → [{mark, text}]: текст между метками <mark name="…"/>
const ssmlSegments = ssml => {
    if (!ssml) return null
    const doc = new DOMParser().parseFromString(ssml, 'application/xml')
    const segments = []
    let cur = { mark: null, text: '' }
    const walker = doc.createTreeWalker(doc.documentElement, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT)
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (n.nodeType === 1 && n.localName === 'mark') {
            if (cur.text.trim()) segments.push(cur)
            cur = { mark: n.getAttribute('name'), text: '' }
        } else if (n.nodeType === 3) cur.text += n.nodeValue
    }
    if (cur.text.trim()) segments.push(cur)
    return segments.map(x => ({ mark: x.mark, text: x.text.replace(/\s+/g, ' ').trim() }))
}
const ttsSend = segments => post({ type: 'tts', segments: segments ?? [] })
const ttsStart = async () => {
    await view.initTTS('sentence', ttsHighlight)
    const range = view.lastLocation?.range
    ttsSend(ssmlSegments(range ? view.tts.from(range) : view.tts.start()))
}
const ttsNext = async () => {
    let segs = ssmlSegments(view.tts?.next())
    // Раздел кончился — переходим к следующему (глава, файл книги), пока не найдём текст
    for (let guard = 0; (!segs || !segs.length) && guard < 10; guard++) {
        const index = view.renderer.getContents?.()[0]?.index
        if (index == null || index + 1 >= view.book.sections.length) break
        await view.renderer.goTo({ index: index + 1 })
        await view.initTTS('sentence', ttsHighlight)
        segs = ssmlSegments(view.tts.start())
    }
    if (!segs || !segs.length) post({ type: 'tts-end' })
    else ttsSend(segs)
}

const onRelocate = ({ detail }) => {
    hideBar()
    const percent = Math.round((detail.fraction ?? 0) * 100)
    const chapter = detail.tocItem?.label?.trim() ?? ''
    $('#percent').textContent = `${percent}%`
    $('#chapter').textContent = chapter
    post({ type: 'relocate', cfi: detail.cfi, fraction: detail.fraction ?? 0, chapter,
        atEnd: !!view?.renderer?.atEnd })
}

// Перевод строк: словарь {русский: перевод} приходит из Python вместе с параметрами книги
let I18N = {}
const T = (s, ...a) => (I18N[s] ?? s).replace(/\{(\d+)\}/g, (_, i) => a[i])

const open = async ({ url, name, cfi, fraction, settings: s, i18n }) => {
    I18N = i18n || {}
    $('#loading').textContent = T('Открываю книгу…')
    try {
        const resp = await fetch(url)
        if (!resp.ok) throw new Error(T('Не удалось прочитать файл ({0})', resp.status))
        const file = new File([await resp.blob()], name)

        view = document.createElement('foliate-view')
        document.body.append(view)
        await view.open(file)

        view.addEventListener('relocate', onRelocate)
        view.addEventListener('load', ({ detail: { doc, index } }) => {
            docIndex.set(doc, index)
            doc.addEventListener('selectionchange', () => onSelectionChange(doc, index))
            paintDoc(doc, index)
            doc.addEventListener('keydown', onKey)
            doc.addEventListener('click', e => onClick(doc, e))
            attachGestures(doc)
        })
        view.addEventListener('external-link', e => {
            e.preventDefault()
            post({ type: 'external-link', href: e.detail.href })
        })

        applySettings(s)
        const { metadata = {}, toc } = view.book
        post({
            type: 'opened',
            title: formatName(metadata.title),
            author: formatName(metadata.author),
            toc: flattenTOC(toc),
        })
        await view.init({ lastLocation: cfi || null, showTextStart: !cfi && !fraction })
        if (!cfi && fraction) await view.goToFraction(fraction)   // PDF: CFI нет
        $('#loading').remove()
    } catch (err) {
        console.error(err)
        $('#loading').textContent = T('Не удалось открыть книгу: {0}', err.message ?? err)
        $('#loading').classList.add('error')
        post({ type: 'error', message: String(err.message ?? err) })
    }
}

document.addEventListener('keydown', onKey)
attachGestures(document)

window.reader = {
    open,
    applySettings,
    next: () => view?.goRight(),
    prev: () => view?.goLeft(),
    goTo: href => view?.goTo(href),
    goToFraction: f => view?.goToFraction(f),
    ttsStart, ttsNext,
    ttsMark: mark => view?.tts?.setMark(mark),
    ttsStop: ttsClear,
    setHighlights,
    goToHighlight,
    // диагностика: по каждому загруженному документу — какие выделения находятся и как
    // результат — в window.__hlDebug (runJavaScript не ждёт асинхронных функций)
    debugHighlights: () => { window.__hlDebug = null; debugHighlights().then(r => { window.__hlDebug = r }) },
}

const debugHighlights = async () => {
        const out = []
        for (const { doc, index } of loadedDocs()) {
            if (!doc) continue
            const items = []
            for (const h of highlights) {
                let viaCfi = null
                if (h.cfi) {
                    try {
                        const r = await view.resolveNavigation(h.cfi)
                        viaCfi = { index: r.index, text: r.index === index ? (r.anchor(doc)?.toString?.() ?? '').slice(0, 40) : null }
                    } catch (e) { viaCfi = { error: String(e).slice(0, 80) } }
                }
                items.push({ id: h.id, section: h.section, viaCfi, viaText: !!findQuote(doc, h) })
            }
            out.push({ index: index ?? null, url: doc.URL.slice(0, 20), text: (doc.body?.textContent ?? '').length, items })
        }
        return JSON.stringify(out)
}

post({ type: 'ready' })
