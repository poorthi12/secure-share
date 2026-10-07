(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const eyeIcon = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 12s3.4-6 9.5-6 9.5 6 9.5 6-3.4 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/></svg>';
  const eyeOffIcon = '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m3 3 18 18M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.2A10.5 10.5 0 0 1 12 5c6.1 0 9.5 7 9.5 7a15 15 0 0 1-2.2 3.1M6.2 6.2C3.8 7.7 2.5 12 2.5 12s3.4 7 9.5 7a10 10 0 0 0 3.2-.5"/></svg>';
  $$('input[type="password"]').forEach((field, index) => {
    const wrapper = document.createElement('span');
    wrapper.className = 'password-input-wrap';
    field.parentNode.insertBefore(wrapper, field);
    wrapper.append(field);

    if (!field.id) {
      let fieldId = `secureshare-password-${index + 1}`;
      while (document.getElementById(fieldId)) fieldId += '-field';
      field.id = fieldId;
    }
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'password-visibility-toggle';
    toggle.setAttribute('aria-label', 'Show password');
    toggle.setAttribute('aria-controls', field.id);
    toggle.setAttribute('aria-pressed', 'false');
    toggle.title = 'Show password';
    toggle.innerHTML = eyeIcon;
    toggle.addEventListener('click', () => {
      const visible = field.type === 'password';
      field.type = visible ? 'text' : 'password';
      toggle.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
      toggle.setAttribute('aria-pressed', String(visible));
      toggle.title = visible ? 'Hide password' : 'Show password';
      toggle.innerHTML = visible ? eyeOffIcon : eyeIcon;
    });
    wrapper.append(toggle);
  });

  const shell = $('.app-shell');
  const menuButton = $('[data-sidebar-toggle]');
  const setSidebar = (open) => {
    shell?.classList.toggle('sidebar-open', open);
    menuButton?.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('drawer-open', open);
  };
  menuButton?.addEventListener('click', () => setSidebar(!shell.classList.contains('sidebar-open')));
  $('[data-sidebar-close]')?.addEventListener('click', () => setSidebar(false));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') setSidebar(false);
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      $('.global-search input')?.focus();
    }
  });

  $$('[data-dismiss]').forEach((button) => button.addEventListener('click', () => button.closest('.flash')?.remove()));
  setTimeout(() => $$('.flash').forEach((item) => item.classList.add('flash-fade')), 7000);
  $$('[data-submit-change]').forEach((control) => control.addEventListener('change', () => {
    if (control.name === 'theme' && ['light', 'dark', 'system'].includes(control.value)) {
      document.documentElement.dataset.theme = control.value;
    }
    control.form?.requestSubmit();
  }));

  const expiry = $('[name="expiry"]');
  const expiryField = $('[data-expiry-field]');
  const updateExpiry = () => {
    if (!expiry || !expiryField) return;
    expiryField.hidden = expiry.value !== 'custom';
    const input = $('input', expiryField);
    if (input) input.required = expiry.value === 'custom';
  };
  expiry?.addEventListener('change', updateExpiry);
  updateExpiry();
  const limit = $('[name="download_limit"]');
  const limitField = $('[data-limit-field]');
  const updateLimit = () => {
    if (!limit || !limitField) return;
    limitField.hidden = limit.value !== 'custom';
    const input = $('input', limitField);
    if (input) input.required = limit.value === 'custom';
  };
  limit?.addEventListener('change', updateLimit);
  updateLimit();

  const input = $('[data-file-input]');
  const zone = $('[data-drop-zone]');
  const fileName = $('[data-file-name]');
  const filePrompt = $('[data-file-prompt]');
  const dropIcon = $('.drop-icon', zone || document);
  const updateFiles = (fileList) => {
    const files = [...(fileList || [])];
    if (!files.length) return;
    zone?.classList.add('has-file');
    if (filePrompt) filePrompt.textContent = files.length === 1 ? 'File ready to upload' : `${files.length} files ready to upload`;
    if (dropIcon) dropIcon.textContent = '\u2713';
    const totalBytes = files.reduce((total, file) => total + file.size, 0);
    const names = files.length <= 2 ? files.map((file) => file.name).join(', ') : `${files.slice(0, 2).map((file) => file.name).join(', ')} + ${files.length - 2} more`;
    if (fileName) fileName.textContent = `${names} \u00B7 ${(totalBytes / 1048576).toFixed(2)} MB total`;
  };
  input?.addEventListener('change', () => updateFiles(input.files));
  ['dragenter', 'dragover'].forEach((name) => zone?.addEventListener(name, (event) => {
    event.preventDefault();
    zone.classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach((name) => zone?.addEventListener(name, (event) => {
    event.preventDefault();
    zone.classList.remove('dragging');
  }));
  zone?.addEventListener('drop', (event) => {
    const files = event.dataTransfer?.files;
    if (files?.length && input) {
      const transfer = new DataTransfer();
      [...files].forEach((file) => transfer.items.add(file));
      input.files = transfer.files;
      updateFiles(input.files);
    }
  });

  const uploadForm = $('[data-upload-form]');
  uploadForm?.addEventListener('submit', (event) => {
    if (!input?.files?.length) return;
    event.preventDefault();
    const progress = $('[data-upload-progress]');
    const bar = $('[data-progress-bar]');
    const value = $('[data-progress-value]');
    const label = $('[data-progress-label]');
    const button = $('[data-submit-button]');
    const data = new FormData(uploadForm);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', uploadForm.action, true);
    xhr.withCredentials = true;
    if (progress) progress.hidden = false;
    if (button) { button.disabled = true; button.textContent = 'Encrypting and uploading…'; }
    xhr.upload.addEventListener('progress', (progressEvent) => {
      if (!progressEvent.lengthComputable) return;
      const percent = Math.round(progressEvent.loaded / progressEvent.total * 100);
      if (bar) bar.style.width = `${percent}%`;
      if (value) value.textContent = `${percent}%`;
      if (label) label.textContent = percent < 100 ? 'Secure upload in progress…' : 'Finalizing encryption…';
    });
    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 400) window.location.assign(xhr.responseURL || '/my-files');
      else {
        if (button) { button.disabled = false; button.textContent = 'Try upload again'; }
        if (label) label.textContent = 'Upload did not complete. Please try again.';
      }
    });
    xhr.addEventListener('error', () => {
      if (button) { button.disabled = false; button.textContent = 'Try upload again'; }
      if (label) label.textContent = 'Connection interrupted. Please try again.';
    });
    xhr.send(data);
  });

  let dialog;
  const getDialog = () => {
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.className = 'confirm-dialog';
    dialog.innerHTML = '<form method="dialog"><span class="dialog-mark">◇</span><h2>Confirm this action</h2><p></p><div><button class="button button-secondary" value="cancel">Cancel</button><button class="button button-danger" value="confirm">Continue</button></div></form>';
    document.body.append(dialog);
    return dialog;
  };
  $$('form[data-confirm]').forEach((form) => form.addEventListener('submit', (event) => {
    if (form.dataset.confirmed === 'true') return;
    event.preventDefault();
    const modal = getDialog();
    $('p', modal).textContent = form.dataset.confirm || 'Are you sure?';
    modal.showModal();
    modal.addEventListener('close', function onClose() {
      modal.removeEventListener('close', onClose);
      if (modal.returnValue === 'confirm') {
        form.dataset.confirmed = 'true';
        form.requestSubmit(event.submitter || undefined);
      }
    });
  }));

  $$('form[data-loading-form]').forEach((form) => form.addEventListener('submit', () => {
    const button = $('button[type="submit"]', form);
    if (!button) return;
    button.disabled = true;
    button.classList.add('is-loading');
    button.setAttribute('aria-busy', 'true');
    button.dataset.originalText = button.textContent.trim();
    button.textContent = 'Please wait...';
  }));

  $$('[data-copy]').forEach((button) => button.addEventListener('click', async () => {
    const field = $('[data-copy-source]', button.closest('.copy-link-row') || document);
    if (!field) return;
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(field.value);
        copied = true;
      }
    } catch {}
    if (!copied) {
      field.focus();
      field.select();
      try { copied = document.execCommand('copy'); } catch {}
    }
    button.textContent = copied ? 'Copied!' : 'Link selected — press Ctrl+C';
    setTimeout(() => { button.textContent = 'Copy link'; }, 2200);
  }));

  // Keep the controls usable if a browser blocks optional enhancements.
  $$('[data-copy-source]').forEach((field) => field.addEventListener('click', () => field.select()));

  const latestNotificationMeta = $('meta[name="notification-latest-id"]');
  if (latestNotificationMeta) {
    let latestNotificationId = latestNotificationMeta.content;
    let shareRefreshPending = false;
    let pollPending = false;
    const refreshBadges = (unreadCount) => {
      const sidebarLink = $('.sidebar a[href="/notifications"]');
      let badge = sidebarLink && $('.nav-badge', sidebarLink);
      if (sidebarLink && unreadCount > 0) {
        if (!badge) {
          badge = document.createElement('span');
          badge.className = 'nav-badge';
          sidebarLink.append(badge);
        }
        badge.textContent = unreadCount > 99 ? '99+' : String(unreadCount);
      } else {
        badge?.remove();
      }
      const notificationButton = $('.top-action-popover > summary');
      let dot = notificationButton && $('.notification-dot', notificationButton);
      if (notificationButton && unreadCount > 0 && !dot) {
        dot = document.createElement('i');
        dot.className = 'notification-dot';
        notificationButton.append(dot);
      } else if (unreadCount === 0) {
        dot?.remove();
      }
      const count = $('[data-notification-count]');
      if (count) {
        count.hidden = unreadCount === 0;
        count.textContent = `${unreadCount} new`;
      }
      const heading = location.pathname === '/notifications' ? $('.page-heading h1') : null;
      let pageCount = $('[data-notification-page-count]') || (heading && $('.count-pill', heading));
      if (heading && unreadCount > 0 && !pageCount) {
        pageCount = document.createElement('span');
        pageCount.className = 'count-pill';
        pageCount.dataset.notificationPageCount = '';
        heading.append(' ', pageCount);
      }
      if (pageCount) {
        pageCount.hidden = unreadCount === 0;
        pageCount.textContent = `${unreadCount} new`;
      }
      const markAll = $('[data-mark-all-read]');
      if (markAll) markAll.hidden = unreadCount === 0;
    };
    const renderPopover = (items) => {
      const preview = $('[data-notification-preview]');
      if (!preview) return;
      preview.replaceChildren();
      if (!items.length) {
        const empty = document.createElement('p');
        empty.textContent = "You're all caught up.";
        preview.append(empty);
        return;
      }
      items.slice(0, 4).forEach((item) => {
        const link = document.createElement('a');
        link.className = `popover-notification${item.read_at ? '' : ' unread'}`;
        link.href = item.target_url || '/notifications';
        link.dataset.notificationId = item.id;
        const title = document.createElement('b');
        title.textContent = item.title || 'Update for you';
        const message = document.createElement('small');
        message.textContent = item.message || '';
        link.append(title, message);
        preview.append(link);
      });
    };
    const showNotification = (item) => {
      const region = $('#toast-region');
      if (!region) return;
      const toast = document.createElement('div');
      toast.className = 'toast';
      toast.setAttribute('role', 'status');
      const copy = document.createElement('span');
      copy.textContent = `${item.title}: ${item.message}`;
      const link = document.createElement('a');
      link.className = 'text-link';
      link.href = item.target_url || '/notifications';
      link.textContent = item.kind === 'share' ? 'View file' : item.kind === 'file_request' ? 'Review request' : 'Open';
      toast.append(copy, document.createTextNode(' '), link);
      region.append(toast);
      setTimeout(() => toast.remove(), 9000);
    };
    const createNotificationElement = (item) => {
      const article = document.createElement('article');
      article.className = `notification-item${item.read_at ? '' : ' unread'}`;
      article.dataset.notificationId = item.id;
      const icon = document.createElement('span');
      icon.className = 'notification-symbol';
      icon.setAttribute('aria-hidden', 'true');
      icon.textContent = item.kind === 'download' ? '\u2193' : item.kind === 'group' ? '\u25C9' : '\u25C7';
      const copy = document.createElement('div');
      copy.className = 'notification-copy';
      const title = document.createElement('strong');
      title.textContent = item.title || 'Update for you';
      const message = document.createElement('p');
      message.textContent = item.message || '';
      copy.append(title, message);
      if (item.target_url) {
        const link = document.createElement('a');
        link.className = 'button button-secondary button-small';
        link.href = item.target_url;
        link.textContent = item.kind === 'share' ? 'View and download' : item.kind === 'file_request' ? 'Review request' : 'Open update';
        copy.append(link);
      }
      const time = document.createElement('time');
      time.textContent = item.created_at ? new Date(item.created_at).toLocaleString() : '';
      copy.append(time);
      article.append(icon, copy);
      if (!item.read_at) {
        const form = document.createElement('form');
        form.method = 'post';
        form.action = `/notifications/${encodeURIComponent(item.id)}/read`;
        const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
        const token = document.createElement('input');
        token.type = 'hidden';
        token.name = '_csrf';
        token.value = csrf;
        const button = document.createElement('button');
        button.className = 'quiet-button';
        button.type = 'submit';
        button.textContent = 'Mark read';
        form.append(token, button);
        article.append(form);
      }
      return article;
    };
    const prependNotification = (item) => {
      const list = $('[data-notification-list]');
      if (!list || list.querySelector(`[data-notification-id="${CSS.escape(item.id)}"]`)) return;
      $('.empty-state', list)?.remove();
      list.prepend(createNotificationElement(item));
    };
    const checkForUpdates = async () => {
      if (document.visibilityState !== 'visible' || pollPending) return;
      pollPending = true;
      try {
        const response = await fetch('/notifications/updates', { credentials: 'same-origin', cache: 'no-store' });
        if (!response.ok) return;
        const updates = await response.json();
        const items = Array.isArray(updates.notifications) ? updates.notifications : updates.latest ? [updates.latest] : [];
        refreshBadges(Number(updates.unread_count || 0));
        renderPopover(items);
        const unseen = [];
        if (latestNotificationId) {
          for (const item of items) {
            if (item.id === latestNotificationId) break;
            unseen.push(item);
          }
        } else {
          unseen.push(...items);
        }
        if (items.length && items[0].id !== latestNotificationId) {
          latestNotificationId = items[0].id;
          latestNotificationMeta.content = latestNotificationId;
          unseen.reverse().forEach((item) => {
            showNotification(item);
            prependNotification(item);
          });
        }
      } catch {} finally {
        pollPending = false;
      }
    };
    void checkForUpdates();
    setInterval(checkForUpdates, 2500);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') void checkForUpdates();
    });
    window.addEventListener('focus', () => void checkForUpdates());

    const sharedFilesPanel = $('[data-shared-signature]');
    if (sharedFilesPanel) {
      const checkSharedFiles = async () => {
        if (document.visibilityState !== 'visible' || shareRefreshPending) return;
        try {
          const response = await fetch('/sharing/updates', { credentials: 'same-origin', cache: 'no-store' });
          if (!response.ok) return;
          const updates = await response.json();
          if (updates.share_signature !== sharedFilesPanel.dataset.sharedSignature) {
            shareRefreshPending = true;
            location.reload();
          }
        } catch {}
      };
      setInterval(checkSharedFiles, 20000);
    }
  }
})();
