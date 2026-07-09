document.querySelectorAll("img").forEach((image) => {
    image.addEventListener("error", () => {
        image.closest(".poster, .details-poster, .cast-member")?.classList.add("image-error");
        image.remove();
    });
});
