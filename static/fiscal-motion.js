'use strict';

// The attached PNG is used byte for byte. Both CSS and canvas only frame its symbol.
window.FiscalMotion = (() => {
    const key = 'fiscalops.visual-preferences.v1';
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    let preferences;
    try { preferences = JSON.parse(localStorage.getItem(key)) || {}; } catch { preferences = {}; }
    preferences = {enabled:preferences.enabled !== false, trail:preferences.trail !== false};
    const rotors = new Set(), surfaces = new Set(), documents = new WeakSet(), frames = new WeakSet();
    const symbol = new Image(); symbol.src = '/static/ssgt-symbol.png';
    let busy = 0, angle = 0, speed = 0, frameId = 0, lastTime = 0;
    const enabled = () => preferences.enabled && !reduced.matches;
    function schedule() { if (!frameId && !document.hidden && enabled()) frameId = requestAnimationFrame(tick); }
    function tick(time) {
        frameId = 0;
        if (!enabled() || document.hidden) return;
        const dt = Math.min((time - (lastTime || time)) / 1000, .05); lastTime = time;
        speed += ((busy ? 270 : 0) - speed) * (1 - Math.exp(-dt * (busy ? 6 : 4)));
        if (!busy && speed < .8) speed = 0;
        angle = (angle + speed * dt) % 360;
        for (const rotor of rotors) {
            if (!rotor.isConnected) rotors.delete(rotor);
            else rotor.style.transform = `rotate(${angle}deg)`;
        }
        let particlesRemain = false;
        for (const surface of surfaces) {
            if (!surface.doc.defaultView || (surface.doc !== document && !surface.doc.defaultView.frameElement?.isConnected)) {
                surface.canvas?.remove(); surfaces.delete(surface); continue;
            }
            const particles = surface.particles = surface.particles.filter(particle => time - particle.born < 620);
            if (!surface.canvas) continue;
            if (!particles.length || !preferences.trail) {
                if (surface.canvas.width !== 1) { surface.canvas.width = 1; surface.canvas.height = 1; }
                surface.particles = []; continue;
            }
            particlesRemain = true;
            const context = surface.context, ratio = surface.ratio;
            context.setTransform(ratio, 0, 0, ratio, 0, 0);
            context.clearRect(0, 0, surface.width, surface.height);
            for (const particle of particles) {
                const life = 1 - (time - particle.born) / 620;
                const size = particle.size * (.55 + .45 * life);
                const drift = (1 - life) * 14;
                context.save(); context.globalAlpha = .26 * life * life;
                context.translate(particle.x + particle.dx * drift, particle.y + drift);
                context.rotate(particle.rotation + (1 - life) * .7);
                context.drawImage(symbol, 345, 51, 520, 520, -size / 2, -size / 2, size, size);
                context.restore();
            }
        }
        if (busy || speed || particlesRemain) schedule(); else lastTime = 0;
    }
    function sync() {
        document.documentElement.dataset.fiscalBusy = String(busy > 0);
        document.documentElement.dataset.fiscalMotion = String(enabled());
        document.documentElement.dataset.mouseTrail = String(enabled() && preferences.trail);
        if (!enabled()) {
            cancelAnimationFrame(frameId); frameId = 0; speed = 0; lastTime = 0;
            for (const surface of surfaces) { surface.particles = []; if (surface.canvas) { surface.canvas.width = 1; surface.canvas.height = 1; } }
        } else if (busy || speed) schedule();
    }
    function begin() {
        busy++; sync(); let finished = false;
        return () => { if (!finished) { finished = true; busy = Math.max(0, busy - 1); sync(); } };
    }
    function setPreferences(changes) {
        preferences = {...preferences, ...changes};
        try { localStorage.setItem(key, JSON.stringify(preferences)); } catch {}
        if (!preferences.trail) for (const surface of surfaces) {
            surface.particles = []; if (surface.canvas) { surface.canvas.width = 1; surface.canvas.height = 1; }
        }
        sync();
    }
    function bindDocument(doc) {
        if (documents.has(doc)) return;
        documents.add(doc);
        const surface = {doc, particles:[], canvas:null, x:0, y:0, lastSpawn:0};
        surfaces.add(surface);
        doc.addEventListener('pointermove', event => {
            if (!enabled() || !preferences.trail || event.pointerType !== 'mouse' || event.buttons || !symbol.complete || !symbol.naturalWidth) return;
            const time = performance.now();
            const distance = Math.hypot(event.clientX - surface.x, event.clientY - surface.y);
            if (time - surface.lastSpawn < 25 || distance < 18) return;
            surface.x = event.clientX; surface.y = event.clientY; surface.lastSpawn = time;
            if (!surface.canvas) {
                const canvas = surface.canvas = doc.createElement('canvas');
                canvas.className = 'fiscal-mouse-trail'; canvas.setAttribute('aria-hidden','true');
                Object.assign(canvas.style, {position:'fixed', inset:'0', width:'100%', height:'100%', pointerEvents:'none', zIndex:'2147483000'});
                // A dialog is in the browser's top layer, above ordinary fixed elements.
                (doc.querySelector('dialog[open]') || doc.body).append(canvas);
                surface.context = canvas.getContext('2d');
                if (!surface.context) { canvas.remove(); surface.canvas = null; return; }
            }
            const host = doc.querySelector('dialog[open]') || doc.body;
            if (surface.canvas.parentElement !== host) host.append(surface.canvas);
            const view = doc.defaultView, ratio = Math.min(view.devicePixelRatio || 1, 1.5);
            const rect = surface.canvas.getBoundingClientRect();
            const width = rect.width || view.innerWidth, height = rect.height || view.innerHeight;
            if (surface.canvas.width !== Math.round(width * ratio) || surface.canvas.height !== Math.round(height * ratio)) {
                surface.canvas.width = Math.round(width * ratio); surface.canvas.height = Math.round(height * ratio);
            }
            Object.assign(surface, {width, height, ratio});
            surface.particles.push({x:event.clientX - rect.left, y:event.clientY - rect.top, born:time, size:14 + Math.random() * 10, dx:Math.random() - .5, rotation:Math.random() * .5});
            if (surface.particles.length > 26) surface.particles.shift();
            schedule();
        }, {passive:true});
    }
    function scan(node) {
        if (!(node instanceof Element)) return;
        if (node.matches('.ssgt-rotor')) rotors.add(node);
        node.querySelectorAll('.ssgt-rotor').forEach(rotor => rotors.add(rotor));
        const candidates = node.matches('iframe') ? [node] : [...node.querySelectorAll('iframe')];
        for (const frame of candidates) {
            if (frames.has(frame)) continue;
            frames.add(frame);
            const bind = () => { try { if (frame.contentDocument?.body) bindDocument(frame.contentDocument); } catch {} };
            frame.addEventListener('load', bind); bind();
        }
    }
    scan(document.body); bindDocument(document);
    new MutationObserver(records => {
        for (const record of records) for (const node of record.addedNodes) scan(node);
    }).observe(document.body, {childList:true, subtree:true});
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, options) => {
        let tracked = false;
        try { const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href); tracked = url.origin === location.origin && url.pathname.startsWith('/api/'); } catch {}
        const end = tracked ? begin() : () => {};
        try { return originalFetch(input, options).finally(end); } catch (error) { end(); throw error; }
    };
    reduced.addEventListener('change', sync);
    document.addEventListener('visibilitychange', () => { lastTime = 0; if (!document.hidden) schedule(); });
    sync();
    return {begin, setPreferences, getPreferences:() => ({...preferences, reduced:reduced.matches})};
})();
