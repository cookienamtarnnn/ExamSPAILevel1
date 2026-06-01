const state = {
  page: 1,
  pageSize: 20,
  totalPages: 1,
  selectedId: null,
  searchTimer: null,
};

const els = {
  dbStatus: document.querySelector("#dbStatus"),
  metricQuestions: document.querySelector("#metricQuestions"),
  metricChoices: document.querySelector("#metricChoices"),
  metricDuplicates: document.querySelector("#metricDuplicates"),
  metricSkipped: document.querySelector("#metricSkipped"),
  searchInput: document.querySelector("#searchInput"),
  resetButton: document.querySelector("#resetButton"),
  resultTitle: document.querySelector("#resultTitle"),
  resultMeta: document.querySelector("#resultMeta"),
  questionList: document.querySelector("#questionList"),
  questionDetail: document.querySelector("#questionDetail"),
  prevPage: document.querySelector("#prevPage"),
  nextPage: document.querySelector("#nextPage"),
  pageInfo: document.querySelector("#pageInfo"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function firstAnswer(value) {
  return String(value || "").trim().slice(0, 1).toUpperCase();
}

function params() {
  const query = new URLSearchParams();
  query.set("page", state.page);
  query.set("page_size", state.pageSize);
  if (els.searchInput.value.trim()) query.set("q", els.searchInput.value.trim());
  return query.toString();
}

async function loadStats() {
  const stats = await fetchJson("/api/stats");
  els.metricQuestions.textContent = stats.questions;
  els.metricChoices.textContent = stats.choices;
  els.metricDuplicates.textContent = stats.duplicates;
  els.metricSkipped.textContent = stats.skipped;
  els.dbStatus.textContent = "Database connected";
}

async function loadQuestions() {
  els.questionList.innerHTML = '<div class="empty-state">Loading questions...</div>';
  const data = await fetchJson(`/api/questions?${params()}`);
  state.totalPages = data.total_pages;
  els.resultTitle.textContent = "Questions";
  els.resultMeta.textContent = `${data.total} matching question${data.total === 1 ? "" : "s"}`;
  els.pageInfo.textContent = `${data.page} / ${data.total_pages}`;
  els.prevPage.disabled = data.page <= 1;
  els.nextPage.disabled = data.page >= data.total_pages;

  if (!data.items.length) {
    els.questionList.innerHTML = '<div class="empty-state">No questions match the current filters.</div>';
    els.questionDetail.innerHTML = '<div class="empty-state">Adjust filters to view questions.</div>';
    return;
  }

  els.questionList.innerHTML = data.items.map((item) => {
    const answer = firstAnswer(item.correct_answer);
    return `
      <button class="question-item ${item.id === state.selectedId ? "active" : ""}" data-id="${item.id}" type="button">
        <div class="question-line">${escapeHtml(item.question_text)}</div>
        <div class="meta">
          <span class="badge">#${escapeHtml(item.source_question_no)}</span>
          ${answer ? `<span class="badge answer">Answer ${escapeHtml(answer)}</span>` : ""}
          <span>${escapeHtml(item.choice_count)} choices</span>
          <span>${escapeHtml(item.source_file)}</span>
        </div>
      </button>
    `;
  }).join("");

  els.questionList.querySelectorAll(".question-item").forEach((button) => {
    button.addEventListener("click", () => selectQuestion(Number(button.dataset.id)));
  });

  if (!state.selectedId || !data.items.some((item) => item.id === state.selectedId)) {
    selectQuestion(data.items[0].id);
  }
}

async function selectQuestion(id) {
  state.selectedId = id;
  els.questionList.querySelectorAll(".question-item").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.id) === id);
  });

  const data = await fetchJson(`/api/questions/${id}`);
  if (data.error) {
    els.questionDetail.innerHTML = `<div class="empty-state">${escapeHtml(data.error)}</div>`;
    return;
  }

  const question = data.question;
  const correct = firstAnswer(question.correct_answer);
  const choices = data.choices.map((choice) => `
    <li class="${firstAnswer(choice.choice_label) === correct ? "correct" : ""}">
      <span class="choiceLabel">${escapeHtml(choice.choice_label)}</span>
      <span>${escapeHtml(choice.choice_text)}</span>
    </li>
  `).join("");

  const duplicateHtml = data.duplicates.length
    ? `
      <div class="sectionTitle">Removed Duplicates</div>
      ${data.duplicates.map((dup) => `
        <div class="note">
          ${escapeHtml(dup.duplicate_source_file)} #${escapeHtml(dup.duplicate_source_question_no)}
        </div>
      `).join("")}
    `
    : "";

  els.questionDetail.innerHTML = `
    <h2>Question ${escapeHtml(question.id)}</h2>
    <div class="questionText">${escapeHtml(question.question_text)}</div>
    <div class="meta">
      <span class="badge">Source #${escapeHtml(question.source_question_no)}</span>
      ${correct ? `<span class="badge answer">Correct ${escapeHtml(question.correct_answer)}</span>` : ""}
      <span>${escapeHtml(question.source_file)}</span>
      <span>${escapeHtml(question.source_sheet)}</span>
    </div>
    <div class="sectionTitle">Choices</div>
    <ul class="choiceList">${choices}</ul>
    ${question.reason ? `<div class="sectionTitle">Reason</div><div class="note">${escapeHtml(question.reason)}</div>` : ""}
    ${question.note ? `<div class="sectionTitle">Note</div><div class="note">${escapeHtml(question.note)}</div>` : ""}
    ${duplicateHtml}
  `;
}

function refreshFromFilters() {
  state.page = 1;
  state.selectedId = null;
  loadQuestions().catch(showError);
}

function showError(error) {
  els.dbStatus.textContent = "Error";
  els.questionList.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
}

els.searchInput.addEventListener("input", () => {
  window.clearTimeout(state.searchTimer);
  state.searchTimer = window.setTimeout(refreshFromFilters, 220);
});
els.resetButton.addEventListener("click", () => {
  els.searchInput.value = "";
  refreshFromFilters();
});
els.prevPage.addEventListener("click", () => {
  if (state.page > 1) {
    state.page -= 1;
    loadQuestions().catch(showError);
  }
});
els.nextPage.addEventListener("click", () => {
  if (state.page < state.totalPages) {
    state.page += 1;
    loadQuestions().catch(showError);
  }
});

loadStats()
  .then(loadQuestions)
  .catch(showError);
