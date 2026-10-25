(() => {
  const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  const weekdays = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
  function calendarDate(year, month, day) {
    const result = new Date(0);
    result.setUTCHours(12,0,0,0);
    result.setUTCFullYear(year,month,day);
    return result;
  }
  function parseDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const [year,month,day] = value.split('-').map(Number);
    const result = calendarDate(year,month-1,day);
    return year>=1 && year<=9999 && result.getUTCFullYear()===year && result.getUTCMonth()===month-1 && result.getUTCDate()===day ? result : null;
  }
  function isoDate(value) {
    return `${String(value.getUTCFullYear()).padStart(4,'0')}-${String(value.getUTCMonth()+1).padStart(2,'0')}-${String(value.getUTCDate()).padStart(2,'0')}`;
  }
  function shiftMonth(value, delta) {
    const first = calendarDate(value.getUTCFullYear(),value.getUTCMonth()+delta,1);
    const last = calendarDate(first.getUTCFullYear(),first.getUTCMonth()+1,0).getUTCDate();
    return calendarDate(first.getUTCFullYear(),first.getUTCMonth(),Math.min(value.getUTCDate(),last));
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {parseDate,isoDate,shiftMonth};
    return;
  }
  const inputs = [...document.querySelectorAll('[data-english-date]')];
  if (!inputs.length) return;
  const todayParts = Object.fromEntries(new Intl.DateTimeFormat('en-GB',{
    timeZone:'Australia/Sydney',year:'numeric',month:'2-digit',day:'2-digit'
  }).formatToParts(new Date()).map(part=>[part.type,part.value]));
  const today = parseDate(`${todayParts.year}-${todayParts.month}-${todayParts.day}`);
  const dialog = document.createElement('dialog');
  dialog.className = 'calendar-dialog';
  dialog.setAttribute('aria-labelledby','calendar-title');
  dialog.innerHTML = `<h2 id="calendar-title">Choose a date</h2>
    <div class="calendar-header"><button type="button" class="secondary" data-month="-1" aria-label="Previous month">←</button><strong aria-live="polite" id="calendar-month"></strong><button type="button" class="secondary" data-month="1" aria-label="Next month">→</button></div>
    <div class="calendar-weekdays" aria-hidden="true">${weekdays.map(day=>`<span>${day}</span>`).join('')}</div>
    <div class="calendar-days" role="group" aria-label="Choose a day"></div>
    <div class="calendar-actions"><button type="button" class="link" data-clear>Clear</button><button type="button" class="secondary" data-today>Today</button><button type="button" data-close>Close</button></div>`;
  document.body.append(dialog);
  const grid = dialog.querySelector('.calendar-days');
  let input,focusDate;
  function allowed(value) {
    const iso = isoDate(value);
    return value.getUTCFullYear()>=1 && value.getUTCFullYear()<=9999 && (!input.dataset.min || iso>=input.dataset.min);
  }
  function render(focusDay=false) {
    const year=focusDate.getUTCFullYear(), month=focusDate.getUTCMonth();
    dialog.querySelector('#calendar-month').textContent = `${months[month]} ${year}`;
    grid.replaceChildren();
    const first=calendarDate(year,month,1), last=calendarDate(year,month+1,0).getUTCDate();
    for (let blank=0;blank<first.getUTCDay();blank++) grid.append(document.createElement('span'));
    for (let day=1;day<=last;day++) {
      const value=calendarDate(year,month,day), iso=isoDate(value);
      const button=document.createElement('button');
      button.type='button';button.textContent=day;button.dataset.date=iso;
      button.disabled=!allowed(value);button.tabIndex=day===focusDate.getUTCDate()?0:-1;
      button.setAttribute('aria-label',new Intl.DateTimeFormat('en-GB',{
        timeZone:'UTC',weekday:'long',day:'numeric',month:'long',year:'numeric'
      }).format(value));
      if (iso===input.value) {button.classList.add('selected');button.setAttribute('aria-pressed','true');}
      if (iso===isoDate(today)) button.setAttribute('aria-current','date');
      grid.append(button);
    }
    dialog.querySelector('[data-month="-1"]').disabled=year===1 && month===0;
    dialog.querySelector('[data-month="1"]').disabled=year===9999 && month===11;
    dialog.querySelector('[data-today]').disabled=!allowed(today);
    if (focusDay) grid.querySelector(`[data-date="${isoDate(focusDate)}"]`)?.focus();
  }
  function choose(value) {
    input.value=value;
    input.dispatchEvent(new Event('input',{bubbles:true}));
    input.dispatchEvent(new Event('change',{bubbles:true}));
    dialog.close();
  }
  dialog.addEventListener('click',event=>{
    const target=event.target.closest('button');
    if (!target || target.disabled) return;
    if (target.dataset.date) choose(target.dataset.date);
    else if (target.dataset.month) {focusDate=shiftMonth(focusDate,Number(target.dataset.month));render();}
    else if (target.hasAttribute('data-today')) choose(isoDate(today));
    else if (target.hasAttribute('data-clear')) choose('');
    else if (target.hasAttribute('data-close')) dialog.close();
  });
  grid.addEventListener('keydown',event=>{
    const offsets={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7};
    let next;
    if (event.key in offsets) next=calendarDate(focusDate.getUTCFullYear(),focusDate.getUTCMonth(),focusDate.getUTCDate()+offsets[event.key]);
    else if (event.key==='PageUp' || event.key==='PageDown') next=shiftMonth(focusDate,event.key==='PageUp'?-1:1);
    else if (event.key==='Home' || event.key==='End') next=calendarDate(focusDate.getUTCFullYear(),focusDate.getUTCMonth(),focusDate.getUTCDate()+(event.key==='Home'?-focusDate.getUTCDay():6-focusDate.getUTCDay()));
    if (next) {event.preventDefault();if(allowed(next)){focusDate=next;render(true);}}
  });
  inputs.forEach(field=>{
    const control=document.createElement('span');control.className='date-control';
    field.before(control);control.append(field);
    const button=document.createElement('button');button.type='button';button.className='calendar-toggle secondary';
    const label=field.closest('label')?.firstChild.textContent.trim() || 'date';
    button.setAttribute('aria-label',`Choose ${label.toLowerCase()}`);button.setAttribute('aria-haspopup','dialog');
    button.textContent='Calendar';control.append(button);
    button.addEventListener('click',()=>{
      input=field;focusDate=parseDate(field.value)||today;
      if(!allowed(focusDate)) focusDate=parseDate(field.dataset.min)||today;
      dialog.querySelector('#calendar-title').textContent=`Choose ${label.toLowerCase()}`;
      render();dialog.showModal();grid.querySelector(`[data-date="${isoDate(focusDate)}"]`)?.focus();
    });
    control.addEventListener('keydown',event=>{
      if(event.altKey && event.key==='ArrowDown'){event.preventDefault();button.click();}
    });
  });
})();
