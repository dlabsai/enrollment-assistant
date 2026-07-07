const withDevTitlePrefix = (title: string): string =>
    import.meta.env.DEV ? `DEV · ${title}` : title;

export const setDocumentTitle = (title: string): void => {
    document.title = withDevTitlePrefix(title);
};
