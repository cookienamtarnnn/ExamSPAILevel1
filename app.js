const state = {
  page: 1,
  pageSize: 20,
  totalPages: 1,
  selectedId: null,
  searchTimer: null,
  data: null,
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

async function loadData() {
  state.data = await fetchJson("data.json");
}

function questionChoices(questionId) {
  return state.data.choicesByQuestion[String(questionId)] || [];
}

function questionDuplicates(questionId) {
  return state.data.duplicatesByQuestion[String(questionId)] || [];
}

function matchesSearch(question, query) {
  if (!query) return true;
  const needle = query.toLowerCase();
  const fields = [
    question.question_text,
    question.note,
    question.reason,
    question.correct_answer,
    question.source_file,
    ...questionChoices(question.id).map((choice) => choice.choice_text),
  ];
  return fields.some((value) => String(value || "").toLowerCase().includes(needle));
}

function getFilteredQuestions() {
  const query = els.searchInput.value.trim();
  return state.data.questions.filter((question) => matchesSearch(question, query));
}

function loadStats() {
  const stats = state.data.stats;
  els.metricQuestions.textContent = stats.questions;
  els.metricChoices.textContent = stats.choices;
  els.metricDuplicates.textContent = stats.duplicates;
  els.metricSkipped.textContent = stats.skipped;
  els.dbStatus.textContent = "Data loaded";
}

function loadQuestions() {
  els.questionList.innerHTML = '<div class="empty-state">Loading questions...</div>';
  const filtered = getFilteredQuestions();
  const total = filtered.length;
  state.totalPages = Math.max(1, Math.ceil(total / state.pageSize));
  if (state.page > state.totalPages) state.page = state.totalPages;
  const start = (state.page - 1) * state.pageSize;
  const items = filtered.slice(start, start + state.pageSize).map((question) => ({
    ...question,
    choice_count: questionChoices(question.id).length,
  }));

  els.resultTitle.textContent = "Questions";
  els.resultMeta.textContent = `${total} matching question${total === 1 ? "" : "s"}`;
  els.pageInfo.textContent = `${state.page} / ${state.totalPages}`;
  els.prevPage.disabled = state.page <= 1;
  els.nextPage.disabled = state.page >= state.totalPages;

  if (!items.length) {
    els.questionList.innerHTML = '<div class="empty-state">No questions match the current filters.</div>';
    els.questionDetail.innerHTML = '<div class="empty-state">Adjust filters to view questions.</div>';
    return;
  }

  els.questionList.innerHTML = items.map((item) => {
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

  if (!state.selectedId || !items.some((item) => item.id === state.selectedId)) {
    selectQuestion(items[0].id);
  }
}

function selectQuestion(id) {
  state.selectedId = id;
  els.questionList.querySelectorAll(".question-item").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.id) === id);
  });

  const question = state.data.questions.find((item) => item.id === id);
  if (!question) {
    els.questionDetail.innerHTML = '<div class="empty-state">Question not found</div>';
    return;
  }
  const choices = questionChoices(id);
  const duplicates = questionDuplicates(id);
  const correct = firstAnswer(question.correct_answer);
  const choicesHtml = choices.map((choice) => `
    <li class="${firstAnswer(choice.choice_label) === correct ? "correct" : ""}">
      <span class="choiceLabel">${escapeHtml(choice.choice_label)}</span>
      <span>${escapeHtml(choice.choice_text)}</span>
    </li>
  `).join("");

  const duplicateHtml = duplicates.length
    ? `
      <div class="sectionTitle">Removed Duplicates</div>
      ${duplicates.map((dup) => `
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
    <ul class="choiceList">${choicesHtml}</ul>
    ${question.reason ? `<div class="sectionTitle">Reason</div><div class="note">${escapeHtml(question.reason)}</div>` : ""}
    ${question.note ? `<div class="sectionTitle">Note</div><div class="note">${escapeHtml(question.note)}</div>` : ""}
    ${duplicateHtml}
  `;
}

function refreshFromFilters() {
  state.page = 1;
  state.selectedId = null;
  loadQuestions();
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
    loadQuestions();
  }
});
els.nextPage.addEventListener("click", () => {
  if (state.page < state.totalPages) {
    state.page += 1;
    loadQuestions();
  }
});

loadData()
  .then(() => {
    loadStats();
    loadQuestions();
  })
  .catch(showError);
