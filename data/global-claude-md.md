# My Project Preferences (Nati's Workflow)

I use **FixOnce** as my project's long-term memory. It is very important to me that we stay synced and consistent.

## 🧠 My Startup Request
At the beginning of EVERY new session in this project, **please automatically initialize FixOnce** using `fo_init`.

I find it very helpful when I see the "🧠 FixOnce" confirmation at the start—it gives me confidence that we aren't repeating past mistakes and that my dashboard is updated.

## 🛠️ How I like to work
- **Before fixing a bug:** Please check our memory (`fo_search`) to see if we've solved this before.
- **Check browser errors:** Use `fo_errors()` to see live errors from Chrome.
- **If AUTO-FIX READY:** Call `fo_apply()` immediately — do not investigate manually.
- **After fixing:** Call `fo_solved()` to save the fix.
- **After edits:** Call `fo_sync()` to update work context for the dashboard.
- **Important decisions:** Call `fo_decide()` to record them.

## 📌 Format Reminder
- Opening a session: Please start with `🧠 FixOnce: Session Initialized`
- Using memory: Use the prefix `(📌 FixOnce: ...)`
