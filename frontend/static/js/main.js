// Bootstrap form validation helper
(function () {
    'use strict'
    const forms = document.querySelectorAll('.needs-validation')
    Array.prototype.slice.call(forms).forEach(function (form) {
      form.addEventListener('submit', function (event) {
        if (!form.checkValidity()) {
          event.preventDefault()
          event.stopPropagation()
        }
        form.classList.add('was-validated')
      }, false)
    })
  })()
  
  // Preview selected image in the upload modal
  const fileInput = document.getElementById('photoInput')
  if (fileInput) {
    fileInput.addEventListener('change', function () {
      const [file] = fileInput.files
      const wrap = document.getElementById('previewWrap')
      const img = document.getElementById('previewImg')
      if (file) {
        img.src = URL.createObjectURL(file)
        wrap.classList.remove('d-none')
      } else {
        wrap.classList.add('d-none')
      }
    })
  }