document.addEventListener('submit', (event) => {
  const question = event.target.dataset.confirm;
  if (question && !window.confirm(question)) event.preventDefault();
});
document.querySelectorAll('[data-quoted-room]').forEach((select) => {
  const updateQuote = () => {
    const rate = select.selectedOptions[0]?.dataset.rate || '';
    select.form.elements.quoted_base.value = rate;
    if (select.form.elements.discount_rate) select.form.elements.discount_rate.max = rate;
  };
  select.addEventListener('change', updateQuote);
  updateQuote();
});
