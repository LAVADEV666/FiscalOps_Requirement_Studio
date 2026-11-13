'use strict';

// One RFC identity across the library, document editor and template designers.
window.CompanyIdentity = (() => {
    const cache = new Map(), targets = new Map();
    const validRfc = value => /^[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}$/.test(value);
    const color = value => /^#[0-9a-f]{6}$/i.test(value || '') ? value : '#63418b';
    async function get(rfc) {
        const current = cache.get(rfc);
        if (current && current.until > Date.now()) return current.promise;
        const promise = fetch('/api/companies/' + encodeURIComponent(rfc) + '/identity', {cache:'no-store'})
            .then(response => { if (!response.ok) throw new Error('Identidad no disponible'); return response.json(); });
        cache.set(rfc, {promise, until:Date.now() + 30000});
        try { return await promise; }
        catch (error) { cache.delete(rfc); throw error; }
    }
    function paint(target, rfc, profile, options) {
        if (!target.isConnected || target.dataset.companyRfc !== rfc) return;
        if (options.registeredOnly && !profile.registered) { target.hidden = true; return; }
        target.hidden = false;
        target.classList.add('company-identity');
        target.classList.toggle('with-company-label', !!options.showName);
        const signature = JSON.stringify([profile, options]);
        if (target.dataset.identitySignature === signature) return;
        target.dataset.identitySignature = signature;
        target.replaceChildren();
        const avatar = document.createElement('span');
        avatar.className = 'company-identity-avatar';
        avatar.style.backgroundColor = color(profile.color || options.color);
        const name = profile.name || options.label || rfc;
        if (profile.registered && profile.cover_version) {
            const image = document.createElement('img');
            image.src = '/api/companies/' + encodeURIComponent(rfc) + '/cover?v=' + encodeURIComponent(profile.cover_version);
            image.alt = 'Portada de ' + name;
            image.onerror = () => { avatar.replaceChildren(document.createTextNode(profile.emoji || options.icon || '🏢')); };
            avatar.append(image);
        } else avatar.textContent = profile.emoji || options.icon || '🏢';
        target.append(avatar);
        target.title = name + ' · ' + rfc;
        if (options.showName) {
            const label = document.createElement('span');
            label.className = 'company-identity-label';
            const heading = document.createElement('strong'), detail = document.createElement('small');
            heading.textContent = name; detail.textContent = rfc;
            label.append(heading, detail); target.append(label);
        }
    }
    async function mount(target, value, options = {}) {
        if (!target) return;
        for (const element of targets.keys()) if (!element.isConnected) targets.delete(element);
        const rfc = String(value || '').trim().toUpperCase();
        target.dataset.companyRfc = rfc;
        if (!validRfc(rfc)) { target.hidden = true; target.replaceChildren(); targets.delete(target); return; }
        targets.set(target, {rfc, options});
        paint(target, rfc, {registered:false}, options);
        try { paint(target, rfc, await get(rfc), options); }
        catch { /* The fallback stays visible; document editing does not depend on company storage. */ }
    }
    function refresh(rfc) {
        cache.delete(rfc);
        for (const [target, context] of targets) {
            if (!target.isConnected) targets.delete(target);
            else if (context.rfc === rfc) mount(target, rfc, context.options);
        }
    }
    window.addEventListener('company:appearance-changed', event => refresh(event.detail.rfc));
    return {mount, refresh};
})();
