/* Mav web app — Ideas: things Mav can do for you, ready to use.
   One of the classic scripts index.html loads in order; they share one
   global scope. Nothing to learn: pick a card, check it, done.
     routine → the routine editor, filled in (you review, then Save)
     chat    → a new chat with the request written for you (edit, then send)
     watch   → a new chat with a /watch request (Mav keeps an eye on it)   */

const IDEA_CATEGORIES = [
  ["all", "Everything"],
  ["money", "Money"],
  ["travel", "Travel"],
  ["home", "Home & family"],
  ["work", "Work"],
  ["learn", "Learn & health"],
];

const IDEAS = [
  // ---------------------------------------------------------------- money
  {
    cat: "money",
    icon: "📊",
    title: "Turn a bank statement into a spreadsheet",
    say: "Here's my statement: sort it by category and give me an Excel file with a chart.",
    does: "Attach a CSV or PDF statement. Mav sorts every line, totals each category and hands you an .xlsx.",
    kind: "chat",
    fill: "Here is my bank statement. Sort every transaction into categories, total each one, and give me an Excel file with a chart of where my money goes.",
  },
  {
    cat: "money",
    icon: "✂️",
    title: "Find subscriptions to cancel",
    say: "Which of my subscriptions could I cancel?",
    does: "Mav asks what you pay for, spots overlaps and what you barely use, and adds up the savings.",
    kind: "chat",
    fill: "Help me find subscriptions I could cancel. Ask me what I pay for each month, then tell me which ones overlap or I barely use, and how much I'd save per year.",
  },
  {
    cat: "money",
    icon: "🧾",
    title: "Bills reminder, on the 1st",
    say: "On the 1st of each month, remind me what's due.",
    does: "A short list of what to pay this month, from what Mav knows about your bills.",
    every: "1st of the month",
    kind: "routine",
    draft: {
      name: "Bills this month",
      prompt:
        "It's the start of the month: list the bills and subscriptions I usually pay this month, with amounts if you know them, and anything unusual to watch for. Ask me to update the list if it looks out of date.",
      mode: "monthly",
      days_of_month: [1],
      time: "09:00",
      agent: "money",
    },
  },
  {
    cat: "money",
    icon: "🏷️",
    title: "Tell me when the price drops",
    say: "Watch this product and tell me when it's under 300 €.",
    does: "Mav checks the price every few hours and only pings you when it drops below your target.",
    kind: "watch",
    fill: "/watch the price of [product or link] — tell me when it drops under [price]",
  },
  // ---------------------------------------------------------------- travel
  {
    cat: "travel",
    icon: "✈️",
    title: "A cheaper flight alert",
    say: "Tell me when a Paris → Lisbon flight in May is under 100 €.",
    does: "Mav keeps looking and comes to you when a fare clears your bar.",
    kind: "watch",
    fill: "/watch flights from [city] to [city] in [month] — tell me when one is under [price]",
  },
  {
    cat: "travel",
    icon: "🗺️",
    title: "Plan a weekend away",
    say: "Plan me a weekend in Lyon, with a day-by-day plan and a budget.",
    does: "Where to stay, what to do, where to eat, how to get there — with a rough budget.",
    kind: "chat",
    fill: "Plan me a weekend in [city] for [number] people: a day-by-day plan, where to stay, where to eat, how to get there, and a rough budget.",
  },
  {
    cat: "travel",
    icon: "🧳",
    title: "Packing list for the trip",
    say: "Make me a packing list for 5 days in Lisbon in May.",
    does: "A checklist that takes the weather and your plans into account, as a file you can keep.",
    kind: "chat",
    fill: "Make me a packing list for [days] days in [place] in [month], taking the weather into account. Give it to me as a checklist file.",
  },
  // ---------------------------------------------------------------- home
  {
    cat: "home",
    icon: "🥗",
    title: "Meal plan and shopping list",
    say: "Every Sunday, plan my dinners and the shopping list.",
    does: "5 simple dinners that fit your diet, and a shopping list grouped by aisle.",
    every: "Sundays",
    kind: "routine",
    draft: {
      name: "Weekly meal plan",
      prompt:
        "Plan 5 simple dinners for this week, with a shopping list grouped by aisle. Take what you know about my diet and household into account.",
      mode: "weekly",
      days: ["sun"],
      time: "10:00",
      agent: "planner",
    },
  },
  {
    cat: "home",
    icon: "🎈",
    title: "Weekend ideas, every Friday",
    say: "On Fridays, give me 3 ideas for the weekend near home.",
    does: "Outings that fit the weather forecast, near where you live.",
    every: "Fridays",
    kind: "routine",
    draft: {
      name: "Weekend ideas",
      prompt:
        "Give me 3 ideas for this weekend near where I live (outings, events, places to try), chosen for the weather forecast. One line each, with the link if there is one.",
      mode: "weekly",
      days: ["fri"],
      time: "17:00",
      agent: "researcher",
    },
  },
  {
    cat: "home",
    icon: "☔",
    title: "Umbrella, only if it rains",
    say: "Tell me in the morning if I need an umbrella.",
    does: "A message at 7, only on days it will rain. Otherwise, silence.",
    every: "Weekday mornings",
    kind: "routine",
    draft: {
      name: "Umbrella if it rains",
      prompt:
        "Tell me whether it will rain today where I live and at what time, so I take an umbrella. If it won't rain, reply exactly: NOTHING TO REPORT",
      mode: "weekly",
      days: ["mon", "tue", "wed", "thu", "fri"],
      time: "07:00",
      agent: "assistant",
    },
  },
  {
    cat: "home",
    icon: "✉️",
    title: "Reply to a tricky message",
    say: "Help me answer my landlord, politely but firmly.",
    does: "Paste the message: Mav drafts a reply in the right tone, ready to copy.",
    kind: "chat",
    fill: "Help me reply to this message, [politely but firmly]. Here it is:\n\n",
  },
  // ---------------------------------------------------------------- work
  {
    cat: "work",
    icon: "☀️",
    title: "Morning briefing",
    say: "Every weekday at 7:30, tell me what matters today.",
    does: "Weather, your calendar and 3 headlines worth knowing, in one short message.",
    every: "Weekdays",
    kind: "routine",
    draft: {
      name: "Morning briefing",
      prompt:
        "Give me a short morning briefing: today's weather where I live, what's in my calendar, and 3 headlines worth knowing. Keep it under 120 words.",
      mode: "weekly",
      days: ["mon", "tue", "wed", "thu", "fri"],
      time: "07:30",
      agent: "researcher",
    },
  },
  {
    cat: "work",
    icon: "🧭",
    title: "Plan my week, on Sunday evening",
    say: "Every Sunday, help me get ahead of the week.",
    does: "Appointments, deadlines, and a realistic plan for the 3 things that matter.",
    every: "Sundays",
    kind: "routine",
    draft: {
      name: "Plan the week",
      prompt:
        "Help me prepare my week: appointments, deadlines, and a realistic plan for the 3 most important things.",
      mode: "weekly",
      days: ["sun"],
      time: "19:00",
      agent: "planner",
    },
  },
  {
    cat: "work",
    icon: "💼",
    title: "New job offers for me",
    say: "Every morning, show me new offers that fit my profile.",
    does: "Mav searches for fresh offers matching what it knows about you, and stays quiet when there's nothing new.",
    every: "Weekdays",
    kind: "routine",
    draft: {
      name: "Job offers",
      prompt:
        "Look for job offers published in the last 24 hours that fit my profile (role, city, remote preference — ask me if you don't know them). List the 5 best with a link and one line on why. If there is nothing new, reply exactly: NOTHING TO REPORT",
      mode: "weekly",
      days: ["mon", "tue", "wed", "thu", "fri"],
      time: "09:00",
      agent: "researcher",
    },
  },
  {
    cat: "work",
    icon: "📄",
    title: "Summarise a long document",
    say: "Turn this 40-page PDF into a one-page summary.",
    does: "Attach the document: Mav reads it and hands you a one-page PDF with the key points.",
    kind: "chat",
    fill: "Read the document I'm attaching and give me a one-page summary as a PDF: the key points, the numbers that matter, and what I need to do.",
  },
  // ---------------------------------------------------------------- learn
  {
    cat: "learn",
    icon: "🎓",
    title: "A 5-minute lesson a day",
    say: "Teach me Spanish, 5 minutes every lunchtime.",
    does: "A short lesson that builds on the previous ones, with a mini quiz.",
    every: "Every day",
    kind: "routine",
    draft: {
      name: "Daily lesson",
      prompt:
        "Give me a 5-minute lesson on what I'm learning (ask me the first time, then remember it), building on the previous lessons in this chat, and end with a 3-question quiz.",
      mode: "daily",
      time: "12:30",
      agent: "assistant",
    },
  },
  {
    cat: "learn",
    icon: "📰",
    title: "News on what I care about",
    say: "Every morning, the 5 headlines on my topics.",
    does: "Headlines with their source and why they matter — no doomscrolling.",
    every: "Every day",
    kind: "routine",
    draft: {
      name: "News digest",
      prompt:
        "Summarise today's news on the topics I care about: 5 headlines at most, each with its source and why it matters.",
      mode: "daily",
      time: "08:00",
      agent: "researcher",
    },
  },
  {
    cat: "learn",
    icon: "🏃",
    title: "A workout plan for the week",
    say: "On Mondays, give me 3 short workouts I can do at home.",
    does: "Three 20-minute sessions, no equipment, adapted to how the last week went.",
    every: "Mondays",
    kind: "routine",
    draft: {
      name: "Weekly workouts",
      prompt:
        "Give me 3 workouts of 20 minutes I can do at home this week without equipment, adapted to my level. Ask me how last week went.",
      mode: "weekly",
      days: ["mon"],
      time: "07:00",
      agent: "planner",
    },
  },
  {
    cat: "learn",
    icon: "💡",
    title: "Explain it simply",
    say: "Explain inflation to me like I'm 12.",
    does: "A clear explanation with an everyday example, then you can dig deeper.",
    kind: "chat",
    fill: "Explain [topic] to me simply, like I'm 12, with an everyday example.",
  },
];

const IDEA_KIND = {
  routine: ["Routine", "Set it up"],
  chat: ["One-off", "Try it"],
  watch: ["Keeps watch", "Set it up"],
};

let ideaFilter = "all";

function renderIdeas() {
  $("#ideaTabs").innerHTML = IDEA_CATEGORIES.map(
    ([id, label]) =>
      `<button class="tab ${id === ideaFilter ? "is-active" : ""}" role="tab" aria-selected="${id === ideaFilter}" data-icat="${id}">${esc(label)}</button>`,
  ).join("");
  $("#ideaGrid").innerHTML = IDEAS.map((x, i) => [x, i])
    .filter(([x]) => ideaFilter === "all" || x.cat === ideaFilter)
    .map(([x, i]) => {
      const [kind, cta] = IDEA_KIND[x.kind];
      const when = x.every ? ` · ${esc(x.every)}` : "";
      return `<article class="idea">
        <span class="idea-ico" aria-hidden="true">${esc(x.icon)}</span>
        <div class="idea-main">
          <h3>${esc(x.title)}</h3>
          <p class="idea-say">“${esc(x.say)}”</p>
          <p class="idea-does">${esc(x.does)}</p>
        </div>
        <footer>
          <span class="badge ${x.kind === "routine" ? "ok" : ""}">${esc(kind)}${when}</span>
          <button class="btn btn-sm ${x.kind === "chat" ? "btn-ghost" : "btn-primary"}" data-idea-use="${i}">${esc(cta)}</button>
        </footer>
      </article>`;
    })
    .join("");
}

/* A request with [placeholders]: select the first one, so typing replaces it. */
function fillComposer(text) {
  const ta = $("#chatInput");
  ta.value = text;
  autoGrow(ta);
  ta.focus();
  const at = text.indexOf("[");
  const end = at >= 0 ? text.indexOf("]", at) : -1;
  if (end > at) ta.setSelectionRange(at, end + 1);
  else ta.setSelectionRange(text.length, text.length);
}

function useIdea(x) {
  if (x.kind === "routine") return editRoutine({ ...x.draft });
  newChat(null);
  setTimeout(() => fillComposer(x.fill), 60);
}

$("#ideaTabs").addEventListener("click", (e) => {
  const t = e.target.closest("[data-icat]");
  if (!t) return;
  ideaFilter = t.dataset.icat;
  renderIdeas();
});
$("#ideaGrid").addEventListener("click", (e) => {
  const b = e.target.closest("[data-idea-use]");
  if (b) useIdea(IDEAS[Number(b.dataset.ideaUse)]);
});
