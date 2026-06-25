// Main JS for Mediador CCT Dashboard

// Auto-close alerts after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            const btn = alert.querySelector('.btn-close');
            if (btn) btn.click();
        }, 5000);
    });
});
