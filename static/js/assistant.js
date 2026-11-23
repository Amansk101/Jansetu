(function () {
  var form = document.getElementById('assistantForm');
  if (!form) return;
  var input = document.getElementById('assistantInput');
  var thread = document.getElementById('assistantThread');
  var suggestions = document.getElementById('assistantSuggestions');
  var tokenEl = form.querySelector('[name=csrfmiddlewaretoken]');
  var endpoint = form.getAttribute('action') || window.location.pathname;
  var sendBtn = form.querySelector('button[type=submit]');
  var busy = false;

  function scrollDown() { thread.scrollTop = thread.scrollHeight; }

  // Render text safely, turning newlines into real line breaks.
  function setText(el, text) {
    el.textContent = '';
    String(text == null ? '' : text).split('\n').forEach(function (line, index) {
      if (index) el.appendChild(document.createElement('br'));
      el.appendChild(document.createTextNode(line));
    });
  }

  function addBubble(text, who) {
    var el = document.createElement('div');
    el.className = 'assistant-bubble assistant-' + who;
    setText(el, text);
    thread.appendChild(el);
    scrollDown();
    return el;
  }

  function addTopics(topics) {
    if (!topics || !topics.length) return;
    var wrap = document.createElement('div');
    wrap.className = 'assistant-topics';
    topics.forEach(function (question) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-outline-secondary btn-sm';
      button.textContent = question;
      button.addEventListener('click', function () { ask(question); });
      wrap.appendChild(button);
    });
    thread.appendChild(wrap);
    scrollDown();
  }

  function setBusy(state) {
    busy = state;
    if (input) input.disabled = state;
    if (sendBtn) sendBtn.disabled = state;
  }

  function ask(question) {
    question = (question || '').trim();
    if (!question || busy) return;
    addBubble(question, 'user');
    input.value = '';
    var thinking = addBubble('…', 'bot');
    setBusy(true);
    fetch(endpoint, {
      method: 'POST',
      headers: { 'X-CSRFToken': tokenEl ? tokenEl.value : '', 'X-Requested-With': 'XMLHttpRequest' },
      body: new URLSearchParams({ question: question })
    }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    }).then(function (data) {
      setText(thinking, data.answer || 'Sorry, I could not find an answer.');
      addTopics(data.suggestions);
    }).catch(function () {
      setText(thinking, 'I could not reach the assistant just now. Please check your connection and try again.');
    }).then(function () {
      setBusy(false);
      if (input) input.focus();
    });
  }

  form.addEventListener('submit', function (event) { event.preventDefault(); ask(input.value); });
  if (suggestions) {
    suggestions.addEventListener('click', function (event) {
      var button = event.target.closest('.suggestion-btn');
      if (button) ask(button.getAttribute('data-q'));
    });
  }
})();
