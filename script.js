// script.js – fetch recaps and render cards
document.addEventListener('DOMContentLoaded', () => {
  const container = document.getElementById('analysis-container');
  fetch('recaps.json')
    .then(res => {
      if (!res.ok) throw new Error('Failed to load recaps.json');
      return res.json();
    })
    .then(data => {
      if (!Array.isArray(data) || data.length === 0) {
        container.innerHTML = '<p class="no-data">No match recaps available.</p>';
        return;
      }
      data.forEach(item => {
        const card = document.createElement('section');
        card.className = 'card';
        const title = document.createElement('h2');
        title.className = 'match-title';
        title.textContent = item.title || 'Untitled';
        const info = document.createElement('p');
        info.className = 'meta';
        info.textContent = item.info || '';
        const recap = document.createElement('pre');
        recap.className = 'recap';
        recap.textContent = item.text || '';
        const btn = document.createElement('button');
        btn.className = 'copy-btn';
        btn.textContent = 'Copy';
        btn.addEventListener('click', () => {
          navigator.clipboard.writeText(item.text || '').then(() => {
            btn.textContent = 'Copied!';
            setTimeout(() => (btn.textContent = 'Copy'), 1500);
          });
        });
        card.appendChild(title);
        card.appendChild(info);
        card.appendChild(recap);
        card.appendChild(btn);
        container.appendChild(card);
      });
    })
    .catch(err => {
      container.innerHTML = `<p class="error">${err.message}</p>`;
    });
});
