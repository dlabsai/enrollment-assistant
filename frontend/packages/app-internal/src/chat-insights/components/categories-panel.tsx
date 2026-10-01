import { Alert, AlertDescription, AlertTitle } from "@va/shared/components/ui/alert";
import { Badge } from "@va/shared/components/ui/badge";
import { Button } from "@va/shared/components/ui/button";
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@va/shared/components/ui/card";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@va/shared/components/ui/dialog";
import {
    Form,
    FormControl,
    FormDescription,
    FormField,
    FormItem,
    FormLabel,
    FormMessage,
} from "@va/shared/components/ui/form";
import { Input } from "@va/shared/components/ui/input";
import { Spinner } from "@va/shared/components/ui/spinner";
import { Switch } from "@va/shared/components/ui/switch";
import { Textarea } from "@va/shared/components/ui/textarea";
import { CircleAlert, Plus } from "lucide-react";
import { type JSX, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { useAuthenticatedApi } from "../../auth/hooks/use-authenticated-api";
import {
    createChatInsightCategory,
    updateChatInsightCategory,
} from "../lib/api";
import type {
    ChatInsightCategory,
    ChatInsightCategoryList,
} from "../types";

interface CategoriesPanelProps {
    categoryList: ChatInsightCategoryList;
    canManage: boolean;
    onChanged: () => void;
}

interface CategoryFormValues {
    name: string;
    description: string;
    includeExamples: string;
    excludeExamples: string;
    active: boolean;
}

const categoryDefaults = (
    category?: ChatInsightCategory,
): CategoryFormValues => ({
    name: category?.name ?? "",
    description: category?.description ?? "",
    includeExamples: category?.include_examples.join("\n") ?? "",
    excludeExamples: category?.exclude_examples.join("\n") ?? "",
    active: category?.active ?? true,
});

const exampleLines = (value: string): string[] =>
    value
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);

const validateExamples = (value: string): true | string => {
    const lines = exampleLines(value);
    if (lines.length > 12) {
        return "Use at most 12 examples";
    }
    if (lines.some((line) => line.length > 500)) {
        return "Each example must be 500 characters or fewer";
    }
    return true;
};

interface CategoryDialogProps {
    category?: ChatInsightCategory;
    onClose: () => void;
    onSaved: () => void;
    open: boolean;
}

const CategoryDialog = ({
    category,
    onClose,
    onSaved,
    open,
}: CategoryDialogProps): JSX.Element => {
    const api = useAuthenticatedApi();
    const [saving, setSaving] = useState(false);
    const form = useForm<CategoryFormValues>({
        defaultValues: categoryDefaults(category),
    });

    useEffect(() => {
        if (open) {
            form.reset(categoryDefaults(category));
        }
    }, [category, form, open]);

    const submit = async (values: CategoryFormValues): Promise<void> => {
        setSaving(true);
        try {
            const input = {
                name: values.name.trim(),
                description: values.description.trim(),
                include_examples: exampleLines(values.includeExamples),
                exclude_examples: exampleLines(values.excludeExamples),
            };
            await (category === undefined
                ? createChatInsightCategory(api, input)
                : updateChatInsightCategory(api, category.key, {
                      ...input,
                      active: values.active,
                  }));
            toast.success(
                category === undefined
                    ? "Topic added; past chats are being updated"
                    : "Topic saved",
            );
            onClose();
            onSaved();
        } catch (error) {
            toast.error(
                error instanceof Error && error.message !== ""
                    ? error.message
                    : "Failed to save topic",
            );
        } finally {
            setSaving(false);
        }
    };

    return (
        <Dialog
            onOpenChange={(nextOpen) => {
                if (!nextOpen && !saving) {
                    onClose();
                }
            }}
            open={open}
        >
            <DialogContent className="sm:max-w-xl">
                <DialogHeader>
                    <DialogTitle>
                        {category === undefined
                            ? "Add topic"
                            : "Edit topic"}
                    </DialogTitle>
                    <DialogDescription>
                        The definition and examples tell the analysis when this
                        topic applies. Changes are applied to past chats before
                        they appear in reports.
                    </DialogDescription>
                </DialogHeader>
                <Form {...form}>
                    <form
                        className="flex flex-col gap-4"
                        id="chat-insight-category-form"
                        onSubmit={(event) => {
                            void form.handleSubmit(submit)(event);
                        }}
                    >
                        <FormField
                            control={form.control}
                            name="name"
                            render={({ field }) => (
                                <FormItem>
                                    <FormLabel>Name</FormLabel>
                                    <FormControl>
                                        <Input
                                            {...field}
                                            disabled={saving}
                                            maxLength={96}
                                            placeholder="e.g. Employer partnerships"
                                        />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                            )}
                            rules={{
                                required: "Name is required",
                                maxLength: {
                                    value: 96,
                                    message: "Use at most 96 characters",
                                },
                                minLength: {
                                    value: 2,
                                    message: "Use at least two characters",
                                },
                            }}
                        />
                        <FormField
                            control={form.control}
                            name="description"
                            render={({ field }) => (
                                <FormItem>
                                    <FormLabel>Definition</FormLabel>
                                    <FormControl>
                                        <Textarea
                                            {...field}
                                            disabled={saving}
                                            maxLength={4000}
                                            placeholder="Describe the topic and when it applies."
                                            rows={4}
                                        />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                            )}
                            rules={{
                                required: "Definition is required",
                                minLength: {
                                    value: 10,
                                    message:
                                        "Use at least ten characters so the topic is distinguishable",
                                },
                            }}
                        />
                        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                            <FormField
                                control={form.control}
                                name="includeExamples"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>Include examples</FormLabel>
                                        <FormControl>
                                            <Textarea
                                                {...field}
                                                disabled={saving}
                                                placeholder="One example per line"
                                                rows={4}
                                            />
                                        </FormControl>
                                        <FormDescription>
                                            Optional; one example per line
                                        </FormDescription>
                                        <FormMessage />
                                    </FormItem>
                                )}
                                rules={{ validate: validateExamples }}
                            />
                            <FormField
                                control={form.control}
                                name="excludeExamples"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>Exclude examples</FormLabel>
                                        <FormControl>
                                            <Textarea
                                                {...field}
                                                disabled={saving}
                                                placeholder="One boundary example per line"
                                                rows={4}
                                            />
                                        </FormControl>
                                        <FormDescription>
                                            Optional; one example per line
                                        </FormDescription>
                                        <FormMessage />
                                    </FormItem>
                                )}
                                rules={{ validate: validateExamples }}
                            />
                        </div>
                        {category !== undefined && (
                            <FormField
                                control={form.control}
                                name="active"
                                render={({ field }) => {
                                    const handleActiveChange = (
                                        checked: boolean,
                                    ): void => {
                                        field.onChange(checked);
                                    };
                                    return (
                                        <FormItem className="flex items-center justify-between rounded-lg border p-3">
                                            <div className="flex flex-col gap-1">
                                                <FormLabel>Active</FormLabel>
                                                <FormDescription>
                                                    Archived topics will no
                                                    longer be assigned after
                                                    the next update.
                                                </FormDescription>
                                            </div>
                                            <FormControl>
                                                <Switch
                                                    checked={field.value}
                                                    disabled={saving}
                                                    onCheckedChange={
                                                        handleActiveChange
                                                    }
                                                />
                                            </FormControl>
                                        </FormItem>
                                    );
                                }}
                            />
                        )}
                    </form>
                </Form>
                <DialogFooter>
                    <Button
                        disabled={saving}
                        onClick={onClose}
                        type="button"
                        variant="outline"
                    >
                        Cancel
                    </Button>
                    <Button
                        disabled={saving}
                        form="chat-insight-category-form"
                        type="submit"
                    >
                        {saving && <Spinner data-icon="inline-start" />}
                        Save topic
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

export const CategoriesPanel = ({
    categoryList,
    canManage,
    onChanged,
}: CategoriesPanelProps): JSX.Element => {
    const [dialogOpen, setDialogOpen] = useState(false);
    const [editing, setEditing] = useState<ChatInsightCategory | undefined>();
    const backfillPending = categoryList.pending_revision !== null;

    return (
        <div className="flex flex-col gap-4">
            {backfillPending && (
                <Alert>
                    <CircleAlert />
                    <AlertTitle>Topic definitions are updating</AlertTitle>
                    <AlertDescription>
                        Current definitions remain in use until past chats have
                        been analyzed with the changes.
                    </AlertDescription>
                </Alert>
            )}
            <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                    <h3 className="font-semibold">Topic definitions</h3>
                    <p className="text-muted-foreground text-sm">
                        Rules used to decide which topics apply to a chat
                    </p>
                </div>
                {canManage && (
                    <Button
                        disabled={backfillPending}
                        onClick={() => {
                            setEditing(undefined);
                            setDialogOpen(true);
                        }}
                    >
                        <Plus data-icon="inline-start" />
                        Add topic
                    </Button>
                )}
            </div>
            <div className="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2">
                {categoryList.categories.map((category) => (
                    <Card key={category.key}>
                        <CardHeader>
                            <div className="flex items-start justify-between gap-3">
                                <div className="flex flex-col gap-1.5">
                                    <CardTitle>{category.name}</CardTitle>
                                    <CardDescription>
                                        {category.description}
                                    </CardDescription>
                                </div>
                                <div className="flex shrink-0 flex-wrap gap-1">
                                    <Badge variant="outline">
                                        {category.origin === "system"
                                            ? "Built-in"
                                            : "Custom"}
                                    </Badge>
                                    {!category.active && (
                                        <Badge variant="secondary">
                                            Archived
                                        </Badge>
                                    )}
                                </div>
                            </div>
                        </CardHeader>
                        {(category.include_examples.length > 0 ||
                            category.exclude_examples.length > 0 ||
                            (canManage && category.origin === "client")) && (
                            <CardContent className="flex flex-col gap-3">
                                {category.include_examples.length > 0 && (
                                    <div className="text-sm">
                                        <span className="font-medium">
                                            Include: {" "}
                                        </span>
                                        {category.include_examples.join(", ")}
                                    </div>
                                )}
                                {category.exclude_examples.length > 0 && (
                                    <div className="text-sm">
                                        <span className="font-medium">
                                            Exclude: {" "}
                                        </span>
                                        {category.exclude_examples.join(", ")}
                                    </div>
                                )}
                                {canManage && category.origin === "client" && (
                                    <Button
                                        className="self-start"
                                        disabled={backfillPending}
                                        onClick={() => {
                                            setEditing(category);
                                            setDialogOpen(true);
                                        }}
                                        size="sm"
                                        variant="outline"
                                    >
                                        Edit
                                    </Button>
                                )}
                            </CardContent>
                        )}
                    </Card>
                ))}
            </div>
            <CategoryDialog
                category={editing}
                onClose={() => {
                    setDialogOpen(false);
                }}
                onSaved={onChanged}
                open={dialogOpen}
            />
        </div>
    );
};
