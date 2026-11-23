document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('[data-confirm]').forEach(el=>el.addEventListener('click',e=>{if(!window.confirm(el.dataset.confirm))e.preventDefault()}));document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',()=>{const button=form.querySelector('button[type="submit"],button:not([type])');if(button&&!button.dataset.busy){button.dataset.busy='1';button.dataset.label=button.innerHTML;button.disabled=true;button.textContent='Please wait…';}}));const action=document.getElementById('officerAction'),remark=document.getElementById('officerRemark');if(action&&remark){const sync=()=>{const decision=['approve','reject'].includes(action.value);remark.required=decision;remark.placeholder=decision?'A reason is required for this final decision':'Add a note for the case record';};action.addEventListener('change',sync);sync();}});
/* Visual refresh: glass public navigation + gentle reveal-on-scroll for cards. */
(function () {
  var nav = document.querySelector('.public-nav');
  if (nav) {
    var onScroll = function () { nav.classList.toggle('is-scrolled', window.scrollY > 8); };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
  }
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce || !('IntersectionObserver' in window)) return;
  var nodes = [].slice.call(document.querySelectorAll('.feature-card,.metric,.module-card,.panel')).filter(function (el) {
    return !el.closest('.hero') && el.getBoundingClientRect().top > window.innerHeight * 0.92;
  });
  if (!nodes.length) return;
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      var el = entry.target;
      el.classList.add('is-visible');
      setTimeout(function () { el.classList.remove('js-reveal', 'is-visible'); }, 700);
      io.unobserve(el);
    });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.05 });
  nodes.forEach(function (el) { el.classList.add('js-reveal'); io.observe(el); });
})();
