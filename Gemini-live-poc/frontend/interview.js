(() => {
  const $ = (selector) => document.querySelector(selector);
  const readyPanel = $("#interview-ready");
  const interviewScreen = $("#interview-screen");
  const resultsPanel = $("#results-panel");
  const transcript = $("#transcript");
  const transcriptDrafts = new Map();
  const playingAudioNodes = new Set();
  let config;
  let socket, audioContext, mediaStream, processor, source;
  let muted = false, ending = false, secondsLeft = 0, timerInterval, nextPlaybackTime = 0, transcriptCount = 0;

  try {
    config = JSON.parse(sessionStorage.getItem("geminiInterviewConfig") || "null");
  } catch {
    config = null;
  }

  if (!config) {
    $("#ready-error").textContent = "Interview setup was not found. Return to setup and submit the configuration first.";
    $("#begin-interview-button").disabled = true;
  } else {
    $("#ready-role").textContent = config.job_role;
    $("#ready-details").textContent = `${config.candidate_name} | ${config.experience_level} | ${config.interview_type} | ${config.duration_minutes} minutes`;
  }

  function connection(online, text) {
    const el = $("#connection-state");
    el.classList.toggle("online", online);
    el.lastChild.textContent = ` ${text}`;
  }

  function voice(state, text) {
    $("#voice-state").textContent = text;
    $("#voice-orb").classList.toggle("listening", state === "listening");
    $("#voice-orb").classList.toggle("speaking", state === "speaking");
  }

  function appendTranscriptChunk(speaker, text) {
    transcript.querySelector(".transcript-empty")?.remove();
    let draft = transcriptDrafts.get(speaker);
    if (!draft) {
      const entry = document.createElement("article");
      entry.className = `transcript-entry ${speaker}`;
      const label = document.createElement("div");
      label.className = "speaker";
      label.textContent = speaker === "candidate" ? "YOU" : "AI INTERVIEWER";
      const words = document.createElement("p");
      entry.append(label, words);
      transcript.append(entry);
      draft = { words };
      transcriptDrafts.set(speaker, draft);
      $("#transcript-count").textContent = String(++transcriptCount);
    }
    draft.words.textContent += text;
    transcript.scrollTop = transcript.scrollHeight;
  }

  function setTimer(remainingSeconds) {
    clearInterval(timerInterval);
    secondsLeft = remainingSeconds;
    const update = () => {
      $("#timer").textContent = `${String(Math.floor(secondsLeft / 60)).padStart(2, "0")}:${String(secondsLeft % 60).padStart(2, "0")}`;
      secondsLeft = Math.max(0, secondsLeft - 1);
    };
    update();
    timerInterval = setInterval(update, 1000);
  }

  function toPcm16(samples, inputRate) {
    const ratio = inputRate / 16000;
    const count = Math.floor(samples.length / ratio);
    const output = new ArrayBuffer(count * 2);
    const view = new DataView(output);
    for (let i = 0; i < count; i += 1) {
      const start = Math.floor(i * ratio);
      const end = Math.min(Math.floor((i + 1) * ratio), samples.length);
      let total = 0;
      for (let j = start; j < end; j += 1) total += samples[j];
      const value = Math.max(-1, Math.min(1, total / Math.max(1, end - start)));
      view.setInt16(i * 2, value < 0 ? value * 32768 : value * 32767, true);
    }
    return output;
  }

  async function startMic() {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    source = audioContext.createMediaStreamSource(mediaStream);
    processor = audioContext.createScriptProcessor(4096, 1, 1);
    processor.onaudioprocess = (event) => {
      if (socket?.readyState === WebSocket.OPEN) {
        const samples = event.inputBuffer.getChannelData(0);
        const chunk = muted
          ? new ArrayBuffer(Math.floor(samples.length * 16000 / audioContext.sampleRate) * 2)
          : toPcm16(samples, audioContext.sampleRate);
        if (chunk.byteLength) socket.send(chunk);
      }
      event.outputBuffer.getChannelData(0).fill(0);
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    $("#mic-button").disabled = false;
    $("#mic-label").textContent = "Microphone on | click to mute";
    voice("listening", "Listening to your answer");
  }

  function playPcm(data) {
    if (ending || !audioContext || data.byteLength < 2) return;
    const input = new DataView(data);
    const samples = new Float32Array(Math.floor(data.byteLength / 2));
    for (let i = 0; i < samples.length; i += 1) {
      const value = input.getInt16(i * 2, true);
      samples[i] = value / (value < 0 ? 32768 : 32767);
    }
    const buffer = audioContext.createBuffer(1, samples.length, 24000);
    buffer.copyToChannel(samples, 0);
    const node = audioContext.createBufferSource();
    node.buffer = buffer;
    node.connect(audioContext.destination);
    playingAudioNodes.add(node);
    const playAt = Math.max(audioContext.currentTime + 0.02, nextPlaybackTime);
    node.start(playAt);
    nextPlaybackTime = playAt + buffer.duration;
    voice("speaking", "AI interviewer is speaking");
    node.onended = () => {
      playingAudioNodes.delete(node);
      node.disconnect();
      if (audioContext && audioContext.currentTime >= nextPlaybackTime - 0.04) voice("listening", "Listening to your answer");
    };
  }

  function cancelScheduledAudio() {
    for (const node of playingAudioNodes) {
      try { node.stop(); } catch { /* The browser may already have ended this chunk. */ }
      node.disconnect();
    }
    playingAudioNodes.clear();
    nextPlaybackTime = audioContext?.currentTime || 0;
  }

  function interruptPlayback() {
    cancelScheduledAudio();
    voice("listening", "Candidate speaking | interviewer listening");
  }

  function stopMic() {
    if (processor) processor.disconnect();
    if (source) source.disconnect();
    if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
    processor = source = mediaStream = null;
    $("#mic-button").disabled = true;
    $("#mic-label").textContent = "Microphone stopped";
  }

  async function closeAudio() {
    cancelScheduledAudio();
    stopMic();
    clearInterval(timerInterval);
    if (audioContext && audioContext.state !== "closed") await audioContext.close();
    audioContext = null;
  }

  async function waitForPlayback() {
    while (audioContext && audioContext.currentTime + 0.03 < nextPlaybackTime) {
      await new Promise((resolve) => setTimeout(resolve, 40));
    }
  }

  function endInterview() {
    if (ending) return;
    ending = true;
    clearInterval(timerInterval);
    stopMic();
    cancelScheduledAudio();
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "end" }));
      $("#end-button").disabled = true;
      voice("", "Finishing interview...");
      connection(true, "Completing your interview");
    } else {
      closeAudio();
    }
  }

  async function handleMessage(event) {
    if (typeof event.data !== "string") {
      playPcm(event.data);
      return;
    }
    let message;
    try { message = JSON.parse(event.data); } catch { return; }

    if (message.type === "connected") {
      $("#role-heading").textContent = message.job_role;
      $("#candidate-heading").textContent = `${message.candidate_name} | ${message.duration_minutes} minute interview`;
      connection(true, "Connected to Gemini Live");
    } else if (message.type === "interview_started") {
      try {
        setTimer(message.remaining_seconds);
        clearInterval(window.interviewSyncInterval);
        window.interviewSyncInterval = setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "ping" }));
        }, 5000);
        await waitForPlayback();
        await startMic();
        $("#end-button").disabled = false;
      } catch (error) {
        $("#interview-error").textContent = `Microphone access failed: ${error.message}`;
        endInterview();
      }
    } else if (message.type === "transcript") {
      appendTranscriptChunk(message.speaker, message.text);
    } else if (message.type === "transcript_final") {
      transcriptDrafts.delete(message.speaker);
    } else if (message.type === "interrupted") {
      interruptPlayback();
    } else if (message.type === "turn_complete") {
      if (!audioContext || audioContext.currentTime >= nextPlaybackTime) voice("listening", "Listening to your answer");
    } else if (message.type === "interview_ended") {
      clearInterval(window.interviewSyncInterval);
      stopMic();
      voice("", "Interview ended");
      connection(false, "Interview ended");
    } else if (message.type === "evaluation_complete") {
      clearInterval(window.interviewSyncInterval);
      await closeAudio();
      $("#results-panel").hidden = false;
      $("#results-summary").textContent = message.report.final_assessment;
      $("#results-score").textContent = `${message.report.overall_score}/100`;
      $("#results-recommendation").textContent = message.report.recommendation;
      const strengths = $("#results-strengths");
      strengths.replaceChildren();
      if (message.report.strengths?.length) {
        const heading = document.createElement("h3");
        heading.textContent = "Strengths";
        strengths.append(heading);
        for (const item of message.report.strengths) {
          const paragraph = document.createElement("p");
          paragraph.className = "result-strength";
          paragraph.textContent = `- ${item}`;
          strengths.append(paragraph);
        }
      }
      $("#results-panel").scrollIntoView({ behavior: "smooth" });
    } else if (message.type === "evaluation_error") {
      clearInterval(window.interviewSyncInterval);
      $("#results-error").textContent = `The interview is complete, but report generation failed: ${message.message}`;
      $("#results-panel").hidden = false;
      await closeAudio();
    } else if (message.type === "transcript_saved") {
      $("#results-error").textContent = `Transcript saved: ${message.artifacts?.transcript_txt || "see output/transcripts"}`;
    } else if (message.type === "pong") {
      if (Number.isFinite(message.remaining_seconds)) {
        secondsLeft = Math.ceil(message.remaining_seconds);
      }
    } else if (message.type === "conclusion_started") {
      if (Number.isFinite(message.remaining_seconds)) secondsLeft = message.remaining_seconds;
    } else if (message.type === "timer_expired") {
      ending = true;
      clearInterval(timerInterval);
      clearInterval(window.interviewSyncInterval);
      stopMic();
      cancelScheduledAudio();
      voice("", "Time is up. Completing your interview...");
      connection(true, "Completing your interview");
    } else if (message.type === "error") {
      $("#interview-error").textContent = message.message || "The interview could not continue.";
      connection(false, "Connection error");
      await closeAudio();
    }
  }

  async function beginInterview() {
    const button = $("#begin-interview-button");
    $("#ready-error").textContent = "";
    button.disabled = true;
    try {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      await audioContext.resume();
    } catch (error) {
      $("#ready-error").textContent = `Audio could not start: ${error.message}`;
      button.disabled = false;
      return;
    }

    readyPanel.hidden = true;
    interviewScreen.hidden = false;
    $("#role-heading").textContent = config.job_role;
    $("#candidate-heading").textContent = `${config.candidate_name} | ${config.duration_minutes} minute interview`;
    $("#end-button").disabled = true;
    voice("", "Connecting to your interviewer...");

    const protocol = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${protocol}://${location.host}/ws/interview`);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => socket.send(JSON.stringify({
      type: "start",
      config,
      client_interview_id: sessionStorage.getItem("geminiInterviewToken"),
    }));
    socket.onmessage = handleMessage;
    socket.onerror = () => { $("#interview-error").textContent = "Could not connect to Gemini Live. Check the server and try again."; };
    socket.onclose = () => {
      if (!ending) {
        connection(false, "Disconnected");
        closeAudio();
      }
    };
  }

  $("#begin-interview-button").addEventListener("click", beginInterview);
  $("#mic-button").addEventListener("click", () => {
    muted = !muted;
    $("#mic-button").classList.toggle("muted", muted);
    $("#mic-label").textContent = muted ? "Microphone muted | click to unmute" : "Microphone on | click to mute";
    voice(muted ? "" : "listening", muted ? "Microphone muted" : "Listening to your answer");
  });
  $("#end-button").addEventListener("click", endInterview);
})();
