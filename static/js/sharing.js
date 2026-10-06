(() => {
  const choices = [...document.querySelectorAll('input[name="share_type"]')];
  const sections = [...document.querySelectorAll('[data-share-fields]')];
  const linkOptions = document.querySelector('[data-link-options]');

  const updateMode = () => {
    const activeMode = choices.find((choice) => choice.checked)?.value;
    sections.forEach((section) => {
      const active = section.dataset.shareFields === activeMode;
      section.hidden = !active;
      section.querySelectorAll('input, select, textarea').forEach((field) => {
        field.disabled = !active;
        field.required = active && field.hasAttribute('data-share-required');
      });
    });
    if (linkOptions) {
      linkOptions.hidden = activeMode !== 'link';
      linkOptions.querySelectorAll('input, select, textarea').forEach((field) => {
        field.disabled = activeMode !== 'link';
        const toggle = field.closest('.password-input-wrap')?.querySelector('.password-visibility-toggle');
        if (toggle) toggle.disabled = field.disabled;
      });
    }
  };

  choices.forEach((choice) => choice.addEventListener('change', updateMode));
  updateMode();
})();
