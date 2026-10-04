const state = {
  config: null,
  articles: [],
  article: null,
  analysis: null,
  activeSentenceId: null,
  selectedText: "",
  selectedSentenceText: "",
  toolResult: null,
  tab: "tools",
  timer: {
    totalSeconds: 25 * 60,
    remainingSeconds: 25 * 60,
    intervalId: null,
    running: false,
  },
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.remove("hidden");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.add("hidden"), 2400);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function sentenceList() {
  if (!state.article) return [];
  return state.article.paragraphs.flatMap((paragraph) => paragraph.sentences);
}

function activeSentence() {
  return sentenceList().find((sentence) => sentence.id === state.activeSentenceId);
}

function currentSelection() {
  const selection = window.getSelection();
  const text = selection ? selection.toString().trim() : "";
  const reader = $("#reader");
  if (!text || !selection.rangeCount || !reader.contains(selection.anchorNode)) {
    return "";
  }
  return text.slice(0, 1200);
}

function selectedRangeRect() {
  const selection = window.getSelection();
  if (!selection || !selection.rangeCount) return null;
  const range = selection.getRangeAt(0);
  const rect = range.getBoundingClientRect();
  if (!rect || (rect.width === 0 && rect.height === 0)) return null;
  return rect;
}

async function loadConfig() {
  state.config = await api("/api/config");
  const label = $("#modeLabel");
  const apiState = $("#apiState");
  if (state.config.ai_mode === "online") {
    label.textContent = "在线增强";
    apiState.textContent = "在线接口已配置，释义、翻译和赏析会优先调用 API。";
  } else {
    label.textContent = "离线演示";
    apiState.textContent = "当前使用离线 mock。配置环境变量后，释义、翻译和赏析会自动走在线接口。";
  }
}

async function loadArticles() {
  const data = await api("/api/articles");
  state.articles = data.articles;
  renderArticleList();
  if (!state.article && state.articles.length) {
    await loadArticle(state.articles[0].id);
  }
}

async function loadArticle(id) {
  state.article = await api(`/api/articles/${id}`);
  state.analysis = null;
  const firstSentence = sentenceList()[0];
  state.activeSentenceId = firstSentence ? firstSentence.id : null;
  state.selectedText = firstSentence ? firstSentence.text : "";
  state.selectedSentenceText = state.selectedText;
  state.toolResult = null;
  renderAll();
  loadAnalysis(false);
}

async function loadAnalysis(refresh = false) {
  if (!state.article) return;
  try {
    state.analysis = await api(`/api/articles/${state.article.id}/analysis${refresh ? "?refresh=1" : ""}`);
    renderAnalysis();
  } catch (error) {
    toast(error.message);
  }
}

function renderAll() {
  renderArticleList();
  renderReader();
  renderInspector();
}

function renderArticleList() {
  $("#articleCount").textContent = state.articles.length;
  const list = $("#articleList");
  if (!state.articles.length) {
    list.innerHTML = `<div class="empty">还没有文章，先导入一篇英文外刊。</div>`;
    return;
  }
  list.innerHTML = state.articles
    .map((article) => {
      const active = state.article && article.id === state.article.id ? "active" : "";
      return `
        <button class="article-card ${active}" data-article-id="${article.id}" type="button">
          <h3>${escapeHtml(article.title)}</h3>
          <p>${escapeHtml(article.source || "本地文章")} · ${article.sentence_count || 0} 句 · ${escapeHtml(article.difficulty)}</p>
        </button>
      `;
    })
    .join("");
}

function renderReader() {
  const article = state.article;
  if (!article) return;
  $("#articleTitle").textContent = article.title;
  $("#articleMeta").textContent = `${article.source || "本地导入"} · ${article.published_at || "未标日期"} · ${article.difficulty}`;
  $("#currentSentence").textContent = activeSentence()?.text || "点击任意句子开始精读。";

  const highlightedIds = new Set(article.highlights.map((item) => item.sentence_id).filter(Boolean));
  $("#reader").innerHTML = article.paragraphs
    .map((paragraph) => {
      const sentences = paragraph.sentences
        .map((sentence) => {
          const active = sentence.id === state.activeSentenceId ? "active" : "";
          const saved = highlightedIds.has(sentence.id) ? "saved" : "";
          return `<span class="sentence ${active} ${saved}" data-sentence-id="${sentence.id}">${escapeHtml(sentence.text)}</span>`;
        })
        .join(" ");
      return `
        <article class="paragraph">
          <div class="paragraph-label">
            <span>P${paragraph.position}</span>
            <span>${escapeHtml(paragraph.role)}</span>
          </div>
          <p>${sentences}</p>
        </article>
      `;
    })
    .join("");
}

function renderInspector() {
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === state.tab));
  $$(".tab-panel").forEach((panel) => panel.classList.add("hidden"));
  $(`#${state.tab}Tab`).classList.remove("hidden");
  $("#selectionText").textContent = state.selectedText || "在正文中划词或选择句子。";
  renderToolResult();
  renderTraining();
  renderAnalysis();
  renderCollections();
  renderNotes();
  renderExport();
}

function renderToolResult() {
  const box = $("#toolResult");
  const result = state.toolResult;
  if (!result) {
    box.innerHTML = "";
    return;
  }
  if (result.type === "lookup") {
    const item = result.data;
    box.innerHTML = `
      <h3>${escapeHtml(item.term)}</h3>
      <p><span class="tag source-pill">${escapeHtml(item.source)}</span> ${escapeHtml(item.pronunciation || "")}</p>
      <p>${escapeHtml(item.definition_cn)}</p>
      <p><strong>${escapeHtml(item.translation_cn || "")}</strong></p>
      <div class="result-actions">
        <button id="saveVocabButton" class="soft-button" type="button">存入单词本</button>
      </div>
    `;
  }
  if (result.type === "translate") {
    const item = result.data;
    box.innerHTML = `
      <h3>翻译</h3>
      <p><span class="tag source-pill">${escapeHtml(item.source)}</span></p>
      <p>${escapeHtml(item.translation_cn)}</p>
      <div class="result-actions">
        <button id="saveHighlightFromTranslation" class="soft-button" type="button">高亮原句</button>
      </div>
    `;
  }
  if (result.type === "pattern") {
    const item = result.data;
    box.innerHTML = `
      <h3>${escapeHtml(item.pattern)}</h3>
      <p><span class="tag source-pill">${escapeHtml(item.source)}</span> ${escapeHtml(item.tags || "")}</p>
      <p>${escapeHtml(item.explanation)}</p>
      <p>${escapeHtml(item.example)}</p>
      <div class="result-actions">
        <button id="savePatternButton" class="soft-button" type="button">存为句型</button>
      </div>
    `;
  }
}

function renderAnalysis() {
  const target = $("#analysisContent");
  if (!state.article) return;
  if (!state.analysis) {
    target.innerHTML = `<div class="empty">正在生成全文赏析与训练题。</div>`;
    return;
  }
  const analysis = state.analysis;
  target.innerHTML = `
    <div class="mini-card">
      <h3>主旨</h3>
      <p>${escapeHtml(analysis.thesis || "")}</p>
      <p><span class="tag source-pill">${escapeHtml(analysis.source || "mock")}</span></p>
    </div>
    <div class="mini-card">
      <h3>段落结构</h3>
      ${(analysis.structure || [])
        .map(
          (item) => `
          <p><strong>P${escapeHtml(item.paragraph)} · ${escapeHtml(item.role)}</strong></p>
          <p>${escapeHtml(item.focus)}</p>
        `,
        )
        .join("")}
    </div>
    <div class="mini-card">
      <h3>文章赏析</h3>
      <ul>${(analysis.appreciation || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </div>
    <div class="mini-card">
      <h3>精读训练</h3>
      <ul>${(analysis.intensive_training || [])
        .map((item) => `<li><strong>${escapeHtml(item.type || "训练")}</strong>：${escapeHtml(item.prompt || item)}</li>`)
        .join("")}</ul>
    </div>
    <div class="mini-card">
      <h3>略读训练</h3>
      <ul>${(analysis.skimming_training || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </div>
  `;
}

function renderTraining() {
  const flowTarget = $("#studyFlow");
  const trainingTarget = $("#ieltsTraining");
  if (!state.article || !flowTarget || !trainingTarget) return;
  renderTimer();
  if (!state.analysis) {
    flowTarget.innerHTML = `<div class="empty">正在准备训练流程。</div>`;
    trainingTarget.innerHTML = `<div class="empty">正在生成雅思题型。</div>`;
    return;
  }
  flowTarget.innerHTML = (state.analysis.study_flow || [])
    .map(
      (item) => `
        <div class="flow-card">
          <div class="flow-time">${escapeHtml(item.minutes)}'</div>
          <div>
            <h3>${escapeHtml(item.phase)}</h3>
            <p>${escapeHtml(item.goal)}</p>
          </div>
        </div>
      `,
    )
    .join("");
  trainingTarget.innerHTML = miniList(
    state.analysis.ielts_training,
    (item, index) => {
      const options = item.options
        ? `<ol class="exercise-options">${item.options.map((option) => `<li>${escapeHtml(option)}</li>`).join("")}</ol>`
        : "";
      const subItems = item.items
        ? item.items
            .map(
              (subItem) => `
                <p><strong>P${escapeHtml(subItem.paragraph)}：</strong>${escapeHtml(subItem.answer)}</p>
                <div class="evidence">${escapeHtml(subItem.evidence)}</div>
              `,
            )
            .join("")
        : "";
      return `
        <div class="exercise-card">
          <div class="exercise-meta">
            <span class="tag">${index + 1}</span>
            <span class="tag source-pill">${escapeHtml(item.type)}</span>
          </div>
          <h3>${escapeHtml(item.question)}</h3>
          ${options}
          ${subItems}
          ${item.answer ? `<p><strong>答案：</strong>${escapeHtml(item.answer)}</p>` : ""}
          ${item.evidence ? `<div class="evidence">${escapeHtml(item.evidence)}</div>` : ""}
        </div>
      `;
    },
    "还没有题型训练。",
  );
}

function renderTimer() {
  const label = $("#timerLabel");
  if (!label) return;
  const minutes = Math.floor(state.timer.remainingSeconds / 60);
  const seconds = state.timer.remainingSeconds % 60;
  label.textContent = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  $("#startTimerButton").textContent = state.timer.running ? "暂停" : "开始";
}

function miniList(items, renderer, emptyText) {
  if (!items || !items.length) return `<div class="empty">${emptyText}</div>`;
  return items.map(renderer).join("");
}

function renderCollections() {
  const article = state.article;
  if (!article) return;
  $("#vocabCount").textContent = article.vocabulary.length;
  $("#patternCount").textContent = article.patterns.length;
  $("#highlightCount").textContent = article.highlights.length;
  $("#vocabList").innerHTML = miniList(
    article.vocabulary,
    (item) => `
      <div class="mini-card">
        <h3>${escapeHtml(item.term)} <span class="tag">${escapeHtml(item.status)}</span></h3>
        <p>${escapeHtml(item.pronunciation)} ${escapeHtml(item.translation_cn)}</p>
        <p>${escapeHtml(item.definition_cn)}</p>
        <div class="status-actions" data-vocab-id="${item.id}">
          <button class="${item.status === "new" ? "active" : ""}" data-status="new" type="button">新学</button>
          <button class="${item.status === "reviewing" ? "active" : ""}" data-status="reviewing" type="button">待复习</button>
          <button class="${item.status === "mastered" ? "active" : ""}" data-status="mastered" type="button">已掌握</button>
        </div>
      </div>
    `,
    "还没有单词。划词后点击释义，再存入单词本。",
  );
  $("#patternList").innerHTML = miniList(
    article.patterns,
    (item) => `
      <div class="mini-card">
        <h3>${escapeHtml(item.pattern)}</h3>
        <p>${escapeHtml(item.explanation)}</p>
        <p>${escapeHtml(item.example)}</p>
      </div>
    `,
    "还没有句型。选中长句后点击句型。",
  );
  $("#highlightList").innerHTML = miniList(
    article.highlights,
    (item) => `
      <div class="mini-card">
        <p>${escapeHtml(item.text)}</p>
        <p>${escapeHtml(item.note || "未添加备注")}</p>
      </div>
    `,
    "还没有高亮。",
  );
}

function renderNotes() {
  const article = state.article;
  if (!article) return;
  $("#noteList").innerHTML = miniList(
    article.notes,
    (item) => `
      <div class="mini-card">
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.body)}</p>
        <p><span class="tag">${escapeHtml(item.tags || "note")}</span></p>
      </div>
    `,
    "还没有笔记。",
  );
}

function renderExport() {
  if (!state.article) return;
  $("#markdownExport").href = `/api/articles/${state.article.id}/export?format=markdown`;
  $("#pdfExport").href = `/api/articles/${state.article.id}/export?format=pdf`;
}

function showSelectionToolbar() {
  const toolbar = $("#selectionToolbar");
  const rect = selectedRangeRect();
  if (!state.selectedText || !rect) {
    toolbar.classList.add("hidden");
    return;
  }
  const top = Math.max(10, rect.top - 46);
  const left = Math.min(window.innerWidth - 250, Math.max(10, rect.left + rect.width / 2 - 120));
  toolbar.style.top = `${top}px`;
  toolbar.style.left = `${left}px`;
  toolbar.classList.remove("hidden");
}

function hideSelectionToolbar() {
  $("#selectionToolbar").classList.add("hidden");
}

function setActiveSentence(id, scroll = false) {
  const sentence = sentenceList().find((item) => item.id === id);
  if (!sentence) return;
  state.activeSentenceId = id;
  state.selectedSentenceText = sentence.text;
  state.selectedText = sentence.text;
  $("#currentSentence").textContent = sentence.text;
  $$(".sentence").forEach((node) => {
    const active = Number(node.dataset.sentenceId) === id;
    node.classList.toggle("active", active);
    if (active && scroll) node.scrollIntoView({ block: "center", behavior: "smooth" });
  });
  renderInspector();
  api("/api/reading-progress", {
    method: "POST",
    body: JSON.stringify({ article_id: state.article.id, current_sentence_id: id, mode: "intensive" }),
  }).catch(() => {});
}

function moveSentence(direction) {
  const list = sentenceList();
  const index = list.findIndex((item) => item.id === state.activeSentenceId);
  const next = list[index + direction];
  if (next) setActiveSentence(next.id, true);
}

function selectionOrSentence() {
  return state.selectedText || activeSentence()?.text || "";
}

async function runLookup() {
  const text = selectionOrSentence();
  if (!text) return toast("先划词或点选一句。");
  const term = text.split(/\s+/).slice(0, 4).join(" ");
  const data = await api("/api/tools/lookup", {
    method: "POST",
    body: JSON.stringify({ term, context: activeSentence()?.text || text }),
  });
  state.toolResult = { type: "lookup", data: data.result };
  state.tab = "tools";
  hideSelectionToolbar();
  renderInspector();
}

async function runTranslate() {
  const text = selectionOrSentence();
  if (!text) return toast("先选择要翻译的文本。");
  const data = await api("/api/tools/translate", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  state.toolResult = { type: "translate", data: data.result };
  state.tab = "tools";
  hideSelectionToolbar();
  renderInspector();
}

async function runPattern() {
  const text = selectionOrSentence();
  if (!text) return toast("先选择一个句子。");
  const data = await api("/api/tools/sentence-analysis", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  state.toolResult = { type: "pattern", data: data.result };
  state.tab = "tools";
  hideSelectionToolbar();
  renderInspector();
}

function speak(text = selectionOrSentence()) {
  if (!text) return toast("先选择要朗读的文本。");
  api("/api/tools/tts", { method: "POST", body: JSON.stringify({ text }) }).catch(() => {});
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.rate = 0.92;
    window.speechSynthesis.speak(utterance);
    toast("正在朗读。");
  } else {
    toast("当前浏览器不支持本地朗读。");
  }
  hideSelectionToolbar();
}

async function refreshArticle() {
  if (!state.article) return;
  const id = state.article.id;
  state.article = await api(`/api/articles/${id}`);
  renderAll();
}

async function saveHighlight(note = "") {
  const text = selectionOrSentence();
  if (!text || !state.article) return toast("先选择文本。");
  await api("/api/highlights", {
    method: "POST",
    body: JSON.stringify({
      article_id: state.article.id,
      sentence_id: state.activeSentenceId,
      text,
      note,
      color: "amber",
    }),
  });
  toast("已高亮。");
  hideSelectionToolbar();
  await refreshArticle();
}

async function saveVocab() {
  if (!state.article || !state.toolResult || state.toolResult.type !== "lookup") return;
  const item = state.toolResult.data;
  await api("/api/vocabulary", {
    method: "POST",
    body: JSON.stringify({
      article_id: state.article.id,
      term: item.term,
      pronunciation: item.pronunciation,
      definition_cn: item.definition_cn,
      translation_cn: item.translation_cn,
      example_sentence: item.example_sentence || activeSentence()?.text || "",
      status: "new",
    }),
  });
  toast("已存入单词本。");
  await refreshArticle();
}

async function updateVocabStatus(id, status) {
  await api("/api/vocabulary/status", {
    method: "POST",
    body: JSON.stringify({ id, status }),
  });
  toast("复习状态已更新。");
  await refreshArticle();
}

function applyNoteTemplate(kind) {
  const title = $("#noteForm input[name='title']");
  const body = $("#noteForm textarea[name='body']");
  const tags = $("#noteForm input[name='tags']");
  if (kind === "summary") {
    title.value = "读后输出";
    tags.value = "输出,summary";
    body.value = [
      "100 字英文 summary：",
      "",
      "作者主张：",
      "",
      "我同意 / 不同意的点：",
      "",
      "可复用表达：",
      "1.",
      "2.",
    ].join("\n");
    return;
  }
  title.value = "雅思阅读复盘";
  tags.value = "雅思,错题,复盘";
  body.value = [
    "段落功能：",
    "P1：",
    "P2：",
    "P3：",
    "",
    "关键词与同义替换：",
    "题干词 -> 原文替换：",
    "",
    "证据句：",
    "",
    "错因：定位失败 / 同义替换未识别 / 主旨误判 / 推断过度",
    "",
    "输出句：",
  ].join("\n");
}

function toggleTimer() {
  if (state.timer.running) {
    window.clearInterval(state.timer.intervalId);
    state.timer.intervalId = null;
    state.timer.running = false;
    renderTimer();
    return;
  }
  state.timer.running = true;
  state.timer.intervalId = window.setInterval(() => {
    state.timer.remainingSeconds = Math.max(0, state.timer.remainingSeconds - 1);
    renderTimer();
    if (state.timer.remainingSeconds === 0) {
      window.clearInterval(state.timer.intervalId);
      state.timer.intervalId = null;
      state.timer.running = false;
      toast("训练时间到，进入复盘。");
      renderTimer();
    }
  }, 1000);
  renderTimer();
}

function resetTimer() {
  window.clearInterval(state.timer.intervalId);
  state.timer.remainingSeconds = state.timer.totalSeconds;
  state.timer.intervalId = null;
  state.timer.running = false;
  renderTimer();
}

async function savePattern() {
  if (!state.article || !state.toolResult || state.toolResult.type !== "pattern") return;
  const item = state.toolResult.data;
  await api("/api/patterns", {
    method: "POST",
    body: JSON.stringify({
      article_id: state.article.id,
      sentence_id: state.activeSentenceId,
      pattern: item.pattern,
      explanation: item.explanation,
      example: item.example,
      tags: item.tags,
    }),
  });
  toast("已存为句型。");
  await refreshArticle();
}

function bindEvents() {
  $("#articleList").addEventListener("click", (event) => {
    const card = event.target.closest("[data-article-id]");
    if (card) loadArticle(Number(card.dataset.articleId)).catch((error) => toast(error.message));
  });

  $("#reader").addEventListener("click", (event) => {
    const sentence = event.target.closest(".sentence");
    if (sentence) setActiveSentence(Number(sentence.dataset.sentenceId), false);
  });

  $("#reader").addEventListener("mouseup", () => {
    const text = currentSelection();
    if (text) {
      state.selectedText = text;
      state.tab = "tools";
      renderInspector();
      showSelectionToolbar();
    }
  });

  document.addEventListener("mousedown", (event) => {
    if (!event.target.closest("#selectionToolbar") && !event.target.closest("#reader")) {
      hideSelectionToolbar();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea")) return;
    if (event.key === "ArrowRight") moveSentence(1);
    if (event.key === "ArrowLeft") moveSentence(-1);
  });

  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.tab = tab.dataset.tab;
      renderInspector();
    });
  });

  $("#prevSentence").addEventListener("click", () => moveSentence(-1));
  $("#nextSentence").addEventListener("click", () => moveSentence(1));
  $("#readSentence").addEventListener("click", () => speak(activeSentence()?.text || ""));
  $("#speakButton").addEventListener("click", () => speak());
  $("#lookupButton").addEventListener("click", () => runLookup().catch((error) => toast(error.message)));
  $("#translateButton").addEventListener("click", () => runTranslate().catch((error) => toast(error.message)));
  $("#patternButton").addEventListener("click", () => runPattern().catch((error) => toast(error.message)));
  $("#highlightButton").addEventListener("click", () => saveHighlight("手动高亮").catch((error) => toast(error.message)));
  $("#clearSelectionButton").addEventListener("click", () => {
    state.selectedText = activeSentence()?.text || "";
    state.toolResult = null;
    window.getSelection()?.removeAllRanges();
    hideSelectionToolbar();
    renderInspector();
  });

  $("#selectionToolbar").addEventListener("click", (event) => {
    const action = event.target.dataset.floatAction;
    if (action === "lookup") runLookup().catch((error) => toast(error.message));
    if (action === "translate") runTranslate().catch((error) => toast(error.message));
    if (action === "speak") speak();
    if (action === "highlight") saveHighlight("划词快捷高亮").catch((error) => toast(error.message));
  });

  $("#toolResult").addEventListener("click", (event) => {
    if (event.target.id === "saveVocabButton") saveVocab().catch((error) => toast(error.message));
    if (event.target.id === "savePatternButton") savePattern().catch((error) => toast(error.message));
    if (event.target.id === "saveHighlightFromTranslation") {
      saveHighlight("翻译后标记").catch((error) => toast(error.message));
    }
  });

  $("#collectionsTab").addEventListener("click", (event) => {
    const button = event.target.closest("[data-status]");
    const wrapper = event.target.closest("[data-vocab-id]");
    if (!button || !wrapper) return;
    updateVocabStatus(Number(wrapper.dataset.vocabId), button.dataset.status).catch((error) =>
      toast(error.message),
    );
  });

  $("#startTimerButton").addEventListener("click", toggleTimer);
  $("#resetTimerButton").addEventListener("click", resetTimer);
  $("#applyIeltsTemplate").addEventListener("click", () => applyNoteTemplate("ielts"));
  $("#applySummaryTemplate").addEventListener("click", () => applyNoteTemplate("summary"));

  $("#newArticleToggle").addEventListener("click", () => $("#importForm").classList.toggle("hidden"));

  $("#importForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form.entries());
    try {
      const data = await api("/api/articles", { method: "POST", body: JSON.stringify(payload) });
      event.currentTarget.reset();
      $("#importForm").classList.add("hidden");
      toast("文章已导入。");
      await loadArticles();
      await loadArticle(data.article.id);
    } catch (error) {
      toast(error.message);
    }
  });

  $("#noteForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.article) return;
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form.entries());
    payload.article_id = state.article.id;
    try {
      await api("/api/notes", { method: "POST", body: JSON.stringify(payload) });
      event.currentTarget.reset();
      toast("笔记已保存。");
      await refreshArticle();
    } catch (error) {
      toast(error.message);
    }
  });
}

async function init() {
  bindEvents();
  try {
    await loadConfig();
    await loadArticles();
  } catch (error) {
    toast(error.message);
  }
}

init();

