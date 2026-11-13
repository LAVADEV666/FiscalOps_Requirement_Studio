'use strict';

function setupManualOcr() {
    const layer = $('#ocrSelectionLayer'), image = $('#pageImage'), dialog = $('#ocrDialog');
    const toggle = $('#ocrToggle'), controls = $('#ocrControls'), hint = $('#ocrHint');
    const read = $('#ocrRead'), remove = $('#ocrRemove'), whole = $('#ocrWholePage');
    const mode = $('#ocrMode'), rotation = $('#ocrRotation');
    const status = $('#ocrStatus'), progress = $('#ocrProgress'), review = $('#ocrReview');
    const recognized = $('#ocrRecognized'), target = $('#ocrTarget'), finalText = $('#ocrFinal');
    const insert = $('#ocrInsert'), replace = $('#ocrReplace'), apply = $('#ocrApply');
    const sourcePreview = $('#ocrSourcePreview'), sourceZone = $('#ocrSourceZone'), crop = $('#ocrCrop');
    const limit = 8;
    const regions = [];
    let active = false, anchor, draft, pointer, busy = false, request = 0;

    function draw() {
        const visible = regions.flatMap((region, index) => region.page === page ? [{...region, number: index + 1}] : []);
        if (draft) visible.push({rect: draft});
        layer.replaceChildren(...visible.map(({rect: [x0, y0, x1, y1], number}) => {
            const box = document.createElement('div');
            box.className = number ? 'ocr-zone' : 'ocr-zone draft';
            Object.assign(box.style, {
                left: Math.min(x0, x1) * 100 + '%', top: Math.min(y0, y1) * 100 + '%',
                width: Math.abs(x0 - x1) * 100 + '%', height: Math.abs(y0 - y1) * 100 + '%',
            });
            if (number) {
                const label = document.createElement('span');
                label.textContent = number;
                box.append(label);
            }
            return box;
        }));
    }

    function updateHint(message = '') {
        const count = regions.length;
        hint.textContent = message || (active
            ? count ? `${count} ${count === 1 ? 'zona marcada' : 'zonas marcadas'} · ${limit - count} disponibles.`
                : 'Arrastra un rectángulo o haz clic en dos esquinas.'
            : 'Relee una zona del PDF.');
        read.disabled = remove.disabled = !count;
        whole.disabled = count >= limit;
    }

    function clearDraft() {
        if (pointer && layer.hasPointerCapture(pointer.id)) layer.releasePointerCapture(pointer.id);
        pointer = anchor = draft = null;
    }

    function setActive(value) {
        active = value;
        if (!value) {
            regions.length = 0;
            clearDraft();
        }
        toggle.setAttribute('aria-pressed', String(value));
        controls.classList.toggle('hidden', !value);
        layer.classList.toggle('active', value);
        draw();
        updateHint();
    }

    function add(rect) {
        clearDraft();
        const [x0, y0, x1, y1] = rect;
        if (Math.min(Math.abs(x1 - x0), Math.abs(y1 - y0)) < .002) {
            draw();
            updateHint('Marca un rectángulo más grande.');
            return;
        }
        if (regions.length < limit) regions.push({page, rect});
        draw();
        updateHint();
    }

    function coordinates(event) {
        const bounds = image.getBoundingClientRect();
        const fraction = (pixel, start, length) => Math.max(0, Math.min(1, (pixel - start) / length));
        return [fraction(event.clientX, bounds.left, bounds.width), fraction(event.clientY, bounds.top, bounds.height)];
    }

    layer.onpointerdown = event => {
        if (!active || event.button !== 0 || !image.naturalWidth || regions.length >= limit) return;
        event.preventDefault();
        const point = coordinates(event);
        if (anchor) {
            add([...anchor, ...point]);
            return;
        }
        pointer = {id: event.pointerId, point, x: event.clientX, y: event.clientY};
        layer.setPointerCapture(event.pointerId);
    };
    layer.onpointermove = event => {
        if (!pointer && !anchor) return;
        draft = [...(pointer?.point || anchor), ...coordinates(event)];
        draw();
    };
    layer.onpointerup = event => {
        if (!pointer || pointer.id !== event.pointerId) return;
        const start = pointer;
        clearDraft();
        if (Math.hypot(event.clientX - start.x, event.clientY - start.y) >= 5) {
            add([...start.point, ...coordinates(event)]);
        } else {
            anchor = start.point;
            updateHint('Haz clic en la esquina opuesta.');
        }
    };
    layer.onpointercancel = () => { clearDraft(); draw(); updateHint(); };
    toggle.onclick = () => setActive(!active);
    whole.onclick = () => add([0, 0, 1, 1]);
    remove.onclick = () => { regions.pop(); clearDraft(); draw(); updateHint(); };
    mode.onchange = () => rotation.classList.toggle('hidden', mode.value === 'auto');
    updateHint();

    function point() {
        return data.points.find(item => item.requirement_id === target.value);
    }

    function syncReview() {
        const hasText = !!recognized.value.trim();
        insert.disabled = replace.disabled = busy || !hasText;
        apply.disabled = busy || !finalText.value.trim() || finalText.value.trim() === point()?.text.trim();
        apply.textContent = point() ? 'Aplicar al numeral' : 'Crear numeral';
        apply.insertAdjacentHTML('afterbegin', desktopIcon('save'));
    }

    function updateTarget() {
        finalText.value = point()?.text ?? recognized.value;
        finalText.setSelectionRange(0, 0);
        syncReview();
    }

    target.onchange = updateTarget;
    recognized.oninput = () => {
        if (!point()) finalText.value = recognized.value;
        syncReview();
    };
    finalText.oninput = syncReview;
    insert.onclick = () => {
        const value = recognized.value.trim();
        if (finalText.value.length - (finalText.selectionEnd - finalText.selectionStart) + value.length > finalText.maxLength) {
            status.textContent = 'La lectura supera el límite de texto del numeral. Selecciona un fragmento mayor o acorta la lectura.';
            return;
        }
        finalText.setRangeText(value, finalText.selectionStart, finalText.selectionEnd, 'select');
        finalText.focus();
        syncReview();
    };
    replace.onclick = () => { finalText.value = recognized.value.trim(); finalText.focus(); syncReview(); };

    function setupSourcePreview(readings) {
        const sources = readings.flatMap(reading => {
            const size = data.pages_manifest?.find(entry => entry.page === reading.page);
            return size?.width && size?.height ? [{...reading, size}] : [];
        });
        sourcePreview.classList.toggle('hidden', !sources.length);
        sourcePreview.open = false;
        crop.replaceChildren();
        sourceZone.replaceChildren(...sources.map((reading, index) => new Option(`Zona ${reading.zone} · Página ${reading.page}`, index)));
        const showCrop = () => {
            const reading = sources[Number(sourceZone.value)];
            if (!sourcePreview.open || !reading) return;
            const {width, height} = reading.size, [x0, y0, x1, y1] = reading.rect;
            crop.setAttribute('viewBox', `${x0 * width} ${y0 * height} ${(x1 - x0) * width} ${(y1 - y0) * height}`);
            const source = document.createElementNS('http://www.w3.org/2000/svg', 'image');
            source.setAttribute('width', width);
            source.setAttribute('height', height);
            source.setAttribute('href', `/api/page/${job}/${reading.page}`);
            crop.replaceChildren(source);
        };
        sourcePreview.ontoggle = showCrop;
        sourceZone.onchange = showCrop;
    }

    read.onclick = async () => {
        if (!regions.length || conflicted) return;
        clearDraft();
        draw();
        const ticket = ++request, forced = mode.value === 'paddle';
        status.textContent = 'Leyendo las zonas en este equipo…';
        progress.classList.remove('hidden');
        review.classList.add('hidden');
        dialog.showModal();
        try {
            const response = await api(`/api/ocr-regions/${job}/preview`, {method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({regions, force_ocr: forced, rotation: forced ? Number(rotation.value) : 0})});
            const {readings} = await response.json();
            if (ticket !== request || !dialog.open) return;
            $('#ocrSources').replaceChildren(...readings.map(reading => {
                const item = document.createElement('li');
                const confidence = reading.confidence === null ? '' : ` · ${Math.round(reading.confidence * 100)}% de confianza`;
                item.className = reading.warning ? 'warning' : '';
                item.textContent = `Zona ${reading.zone} · Página ${reading.page} · ${reading.warning || (reading.method === 'native' ? 'Texto del PDF' : 'PaddleOCR' + confidence)}`;
                return item;
            }));
            setupSourcePreview(readings);
            recognized.value = readings.map(item => item.text).filter(Boolean).join('\n\n').slice(0, recognized.maxLength);
            target.replaceChildren(...data.points.map(item => new Option('Numeral ' + item.number, item.requirement_id)),
                new Option('Crear el siguiente numeral', ''));
            const firstPage = readings[0].page;
            const linked = data.points.find(item => item.requirement_id === selected) ||
                data.points.find(item => item.page_start <= firstPage && item.page_end >= firstPage);
            target.value = linked?.requirement_id ?? '';
            updateTarget();
            review.classList.remove('hidden');
            status.textContent = recognized.value ? 'Contrasta la lectura con el PDF y confirma el texto final.'
                : 'Puedes transcribir la zona y guardarla como texto del numeral.';
        } catch (error) {
            if (ticket === request) status.textContent = error.message;
        } finally {
            if (ticket === request) progress.classList.add('hidden');
        }
    };

    apply.onclick = async () => {
        if (busy || conflicted) return;
        busy = true;
        apply.setAttribute('aria-busy', 'true');
        $('#ocrClose').disabled = target.disabled = finalText.disabled = recognized.disabled = true;
        syncReview();
        status.textContent = 'Guardando la corrección…';
        try {
            if ((dirty || saveFlight) && !await save(true)) throw new Error('Guarda el expediente antes de aplicar la lectura.');
            const response = await api(`/api/ocr-regions/${job}/apply`, {method: 'POST', headers: {'Content-Type':'application/json'},
                body: JSON.stringify({regions, requirement_id: target.value || null,
                    expected_revision: data.workspace_revision, text: finalText.value})});
            const result = await response.json();
            snapshot();
            data = result.data;
            selected = result.requirement_id;
            dialog.close();
            setActive(false);
            renderAll();
            renderOverlay();
            focusCard(selected);
            toast('Lectura aplicada al expediente');
        } catch (error) {
            status.textContent = error.message;
        } finally {
            busy = false;
            $('#ocrClose').disabled = target.disabled = finalText.disabled = recognized.disabled = false;
            apply.removeAttribute('aria-busy');
            syncReview();
        }
    };
    dialog.oncancel = event => { if (busy) event.preventDefault(); };
    dialog.addEventListener('close', () => { if (!dialog.open) request++; });
    return {
        pageChanged() { clearDraft(); draw(); updateHint(); },
        start() { setActive(true); toggle.focus(); },
        cancel() { if (active) { setActive(false); return true; } return false; },
    };
}
