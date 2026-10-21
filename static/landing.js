// The landing page: sections that fade up as they scroll in, and the contact
// form, which posts to /api/contact and says how it went. The server does the
// real validation; the checks here only save a round trip.

(function () {
  // Reveal on scroll. The page is only marked once the observer exists, so
  // without it (or without this script) every section is simply visible.
  const items = document.querySelectorAll(".reveal");
  if (items.length && "IntersectionObserver" in window) {
    document.documentElement.classList.add("js-reveal");
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    // Siblings in a row come in one after another rather than all at once.
    items.forEach((item) => {
      const siblings = [...item.parentElement.children].filter((el) => el.classList.contains("reveal"));
      item.style.transitionDelay = Math.min(siblings.indexOf(item), 4) * 80 + "ms";
      observer.observe(item);
    });
  }
})();

(function () {
  const form = document.getElementById("contact-form");
  if (!form) return;

  const $ = (id) => document.getElementById(id);
  const submit = $("contact-submit");

  function say(box, message) {
    $("contact-error").hidden = true;
    $("contact-note").hidden = true;
    if (!message) return;
    $(box).textContent = message;
    $(box).hidden = false;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = {
      name: $("contact-name").value.trim(),
      email: $("contact-email").value.trim(),
      message: $("contact-message").value.trim(),
      website: $("contact-website").value,
    };
    if (!data.name || !data.email || !data.message) {
      say("contact-error", "Please fill in your name, email and message.");
      return;
    }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(data.email)) {
      say("contact-error", "That doesn't look like a valid email address.");
      return;
    }

    say(null);
    submit.disabled = true;
    submit.textContent = "Sending…";
    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.error || "Could not send your message.");
      $("contact-message").value = "";
      say("contact-note", "Thanks, your message is on its way. We'll reply by email.");
    } catch (error) {
      say("contact-error", error.message || "Could not send your message.");
    } finally {
      submit.disabled = false;
      submit.textContent = "Send message";
    }
  });
})();
