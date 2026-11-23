(() => {
  const form = document.querySelector("#setup-form");
  const submitButton = document.querySelector("#submit-config-button");
  const error = document.querySelector("#setup-error");

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    error.textContent = "";
    if (!form.reportValidity()) return;

    const values = new FormData(form);
    const config = {
      candidate_name: String(values.get("candidate_name")).trim(),
      job_role: String(values.get("job_role")).trim(),
      experience_level: values.get("experience_level"),
      interview_type: values.get("interview_type"),
      duration_minutes: Number(values.get("duration_minutes")),
      topics: String(values.get("topics") || "").split(",").map((topic) => topic.trim()).filter(Boolean),
      job_description: String(values.get("job_description") || "").trim(),
    };

    try {
      sessionStorage.setItem("geminiInterviewConfig", JSON.stringify(config));
      sessionStorage.setItem("geminiInterviewToken", crypto.randomUUID());
      submitButton.disabled = true;
      window.location.assign("/interview");
    } catch (storageError) {
      error.textContent = `Could not save the interview setup in this browser: ${storageError.message}`;
    }
  });
})();
