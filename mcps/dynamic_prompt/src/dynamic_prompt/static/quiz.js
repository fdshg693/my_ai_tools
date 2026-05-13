let currentQuiz = null;
let submitted = false;

// --- Render quiz ---
function renderQuiz(data) {
  currentQuiz = data;
  submitted = false;

  // Auto-fill language code for word input
  if (data.lang) {
    document.getElementById("word-lang").value = data.lang;
  }

  document.getElementById("waiting").style.display = "none";
  document.getElementById("results-summary").style.display = "none";
  document.getElementById("quiz-area").style.display = "block";
  document.getElementById("quiz-title").textContent = data.title || "Quiz";
  document.getElementById("submit-btn").disabled = false;

  const container = document.getElementById("questions-container");
  container.innerHTML = "";

  data.questions.forEach((q, qi) => {
    const card = document.createElement("div");
    card.className = "question-card";
    card.dataset.qi = qi;

    const numEl = document.createElement("div");
    numEl.className = "question-number";
    numEl.textContent = `Question ${qi + 1}`;
    card.appendChild(numEl);

    const textEl = document.createElement("div");
    textEl.className = "question-text";
    textEl.textContent = q.question;
    card.appendChild(textEl);

    const qtype = q.question_type || "mc";

    if (qtype === "free") {
      // Free-answer: textarea input
      const freeArea = document.createElement("div");
      freeArea.className = "free-answer-area";

      const textarea = document.createElement("textarea");
      textarea.className = "free-answer-input";
      textarea.name = `q${qi}`;
      textarea.placeholder = "Type your answer here...";
      textarea.rows = 3;

      freeArea.appendChild(textarea);
      card.appendChild(freeArea);

      // Badge indicating free-answer type
      const badge = document.createElement("span");
      badge.className = "question-type-badge free";
      badge.textContent = "Free Answer";
      numEl.appendChild(badge);
    } else {
      // Multiple-choice: radio buttons
      const choicesEl = document.createElement("div");
      choicesEl.className = "choices";

      q.choices.forEach((c, ci) => {
        const label = document.createElement("label");
        label.className = "choice-label";
        label.dataset.ci = ci;

        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = `q${qi}`;
        radio.value = ci;
        radio.addEventListener("change", () => {
          label.parentElement.querySelectorAll(".choice-label").forEach(l => l.classList.remove("selected"));
          label.classList.add("selected");
        });

        const span = document.createElement("span");
        span.textContent = c;

        label.appendChild(radio);
        label.appendChild(span);
        choicesEl.appendChild(label);
      });

      card.appendChild(choicesEl);
    }

    container.appendChild(card);
  });

  window.scrollTo({ top: 0, behavior: "smooth" });
}

// --- Submit answers ---
document.getElementById("quiz-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (submitted || !currentQuiz) return;

  const answers = currentQuiz.questions.map((q, qi) => {
    const qtype = q.question_type || "mc";
    if (qtype === "free") {
      const textarea = document.querySelector(`textarea[name="q${qi}"]`);
      return textarea ? textarea.value.trim() : "";
    } else {
      const selected = document.querySelector(`input[name="q${qi}"]:checked`);
      return selected ? parseInt(selected.value) : -1;
    }
  });

  // Validate: check all MC questions are answered and all free questions have text
  for (let i = 0; i < answers.length; i++) {
    const qtype = currentQuiz.questions[i].question_type || "mc";
    if (qtype === "mc" && answers[i] === -1) {
      alert("Please answer all multiple-choice questions before submitting.");
      return;
    }
    if (qtype === "free" && answers[i] === "") {
      alert("Please fill in all free-answer questions before submitting.");
      return;
    }
  }

  submitted = true;
  document.getElementById("submit-btn").disabled = true;

  try {
    const resp = await fetch("/api/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: currentQuiz.session_id, answers }),
    });
    const result = await resp.json();
    showResults(result);
  } catch (err) {
    alert("Error submitting: " + err.message);
    submitted = false;
    document.getElementById("submit-btn").disabled = false;
  }
});

// --- Show results ---
function showResults(result) {
  const { correct_count, total_count, mc_total, has_free, details } = result;

  // Highlight each question
  details.forEach((d) => {
    const card = document.querySelector(`.question-card[data-qi="${d.question_index}"]`);
    if (!card) return;

    if (d.question_type === "free") {
      // Free answer: show "awaiting scoring" or scored result
      card.classList.add("free-submitted");
      const textarea = card.querySelector("textarea");
      if (textarea) {
        textarea.disabled = true;
        textarea.classList.add("disabled");
      }
      // Add a status message
      const statusEl = document.createElement("div");
      statusEl.className = "free-answer-status pending";
      statusEl.textContent = "Awaiting AI scoring...";
      card.appendChild(statusEl);
    } else {
      // MC answer: show correct/incorrect
      card.classList.add(d.is_correct ? "correct" : "incorrect");

      const labels = card.querySelectorAll(".choice-label");
      labels.forEach((label) => {
        label.classList.add("disabled");
        const ci = parseInt(label.dataset.ci);
        if (ci === d.correct_index) {
          label.classList.add("correct-choice");
        }
        if (ci === d.user_answer && !d.is_correct) {
          label.classList.add("incorrect-choice");
        }
      });
    }
  });

  // Show summary
  const summary = document.getElementById("results-summary");
  const mcCount = mc_total || total_count;

  if (has_free) {
    document.getElementById("score-value").textContent = `${correct_count} / ${mcCount} (MC)`;
    document.getElementById("score-label").textContent =
      `${mcCount > 0 ? Math.round((correct_count / mcCount) * 100) : 0}% correct (MC) \u2014 Free answers pending AI scoring`;
  } else {
    const pct = total_count > 0 ? Math.round((correct_count / total_count) * 100) : 0;
    document.getElementById("score-value").textContent = `${correct_count} / ${total_count}`;
    document.getElementById("score-label").textContent = `${pct}% correct`;
  }

  const pctForBar = mcCount > 0 ? Math.round((correct_count / mcCount) * 100) : 0;
  document.getElementById("score-bar-fill").style.width = `${pctForBar}%`;
  summary.style.display = "block";

  // Scroll to summary
  summary.scrollIntoView({ behavior: "smooth", block: "start" });
}

// --- SSE connection ---
function connectSSE() {
  const es = new EventSource("/events");

  es.addEventListener("quiz", (e) => {
    try {
      const data = JSON.parse(e.data);
      renderQuiz(data);
      setStatus("connected", "Quiz received");
    } catch (err) {
      console.error("Failed to parse quiz data:", err);
    }
  });

  es.addEventListener("ping", () => {});

  es.onopen = () => {
    setStatus("connected", "Connected");
  };

  es.onerror = () => {
    setStatus("waiting", "Reconnecting...");
  };
}

function setStatus(type, text) {
  const badge = document.getElementById("status");
  badge.className = `status-badge ${type}`;
  document.getElementById("status-text").textContent = text;
}

// --- Init ---
async function init() {
  // Check for pending quiz
  try {
    const resp = await fetch("/api/pending");
    const data = await resp.json();
    if (data && data.session_id) {
      renderQuiz(data);
      setStatus("connected", "Quiz loaded");
    } else {
      setStatus("waiting", "Waiting for quiz...");
    }
  } catch {
    setStatus("waiting", "Waiting for quiz...");
  }

  connectSSE();
}

// --- Word input toggle ---
document.getElementById("word-toggle").addEventListener("click", () => {
  const toggle = document.getElementById("word-toggle");
  const body = document.getElementById("word-body");
  toggle.classList.toggle("open");
  body.classList.toggle("open");
});

// --- Word save ---
document.getElementById("word-save-btn").addEventListener("click", async () => {
  const wordsInput = document.getElementById("word-input");
  const langInput = document.getElementById("word-lang");
  const contextInput = document.getElementById("word-context");
  const feedback = document.getElementById("word-feedback");
  const btn = document.getElementById("word-save-btn");

  const words = wordsInput.value.trim();
  const lang = langInput.value.trim();

  if (!words) {
    feedback.textContent = "Please enter at least one word.";
    feedback.className = "word-feedback error";
    return;
  }
  if (!lang) {
    feedback.textContent = "Please enter a language code.";
    feedback.className = "word-feedback error";
    return;
  }

  btn.disabled = true;
  feedback.textContent = "";

  try {
    const resp = await fetch("/api/save_words", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        lang,
        words,
        context: contextInput.value.trim(),
      }),
    });
    const result = await resp.json();
    if (resp.ok) {
      feedback.textContent = `Saved ${result.count} word(s): ${result.saved.join(", ")}`;
      feedback.className = "word-feedback success";
      wordsInput.value = "";
      contextInput.value = "";
    } else {
      feedback.textContent = result.error || "Failed to save.";
      feedback.className = "word-feedback error";
    }
  } catch (err) {
    feedback.textContent = "Error: " + err.message;
    feedback.className = "word-feedback error";
  } finally {
    btn.disabled = false;
  }
});

init();
