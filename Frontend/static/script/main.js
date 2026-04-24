document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.getElementById("sidebarToggle");
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("sidebarOverlay");

    if (toggle && sidebar) {
        const openSidebar = () => {
            sidebar.classList.add("open");
            overlay?.classList.add("show");
            toggle.setAttribute("aria-expanded", "true");
        };

        const closeSidebar = () => {
            sidebar.classList.remove("open");
            overlay?.classList.remove("show");
            toggle.setAttribute("aria-expanded", "false");
        };

        toggle.addEventListener("click", () => {
            sidebar.classList.contains("open") ? closeSidebar() : openSidebar();
        });

        overlay?.addEventListener("click", closeSidebar);

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeSidebar();
            }
        });

        sidebar.querySelectorAll("a").forEach((link) => {
            link.addEventListener("click", () => {
                if (window.matchMedia("(max-width: 991.98px)").matches) {
                    closeSidebar();
                }
            });
        });
    }

    const autoRefresh = document.querySelector("[data-auto-refresh]");
    if (autoRefresh) {
        const delay = Number(autoRefresh.dataset.autoRefresh || 15000);
        window.setInterval(() => {
            if (!document.hidden) {
                window.location.reload();
            }
        }, delay);
    }

    document.querySelectorAll(".hd-table-action-form").forEach((form) => {
        const actionSelect = form.querySelector(".appointment-action-select");
        if (!actionSelect) return;

        const dateField = form.querySelector(".appointment-extra-date");
        const timeField = form.querySelector(".appointment-extra-time");
        const doctorField = form.querySelector(".appointment-extra-doctor");
        const extras = [dateField, timeField, doctorField].filter(Boolean);

        const syncFields = () => {
            const action = actionSelect.value;
            const needsDateTime = action === "reschedule" || action === "reassign";
            const needsDoctor = action === "reassign";

            extras.forEach((field) => {
                field.classList.add("is-hidden");
                field.required = false;
            });

            [dateField, timeField].filter(Boolean).forEach((field) => {
                field.classList.toggle("is-hidden", !needsDateTime);
                field.required = needsDateTime;
            });

            if (doctorField) {
                doctorField.classList.toggle("is-hidden", !needsDoctor);
                doctorField.required = needsDoctor;
            }
        };

        actionSelect.addEventListener("change", syncFields);
        syncFields();
    });
});
