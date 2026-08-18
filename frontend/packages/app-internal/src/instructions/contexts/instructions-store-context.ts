import { createContext, use } from "react";
import { useStore } from "zustand";

import type {
    InstructionsActions,
    InstructionsStore,
    InstructionsStoreState,
} from "../lib/store";

export const InstructionsStoreContext = createContext<
    InstructionsStore | undefined
>(undefined);

const useInstructionsStoreContext = (): InstructionsStore => {
    const value = use(InstructionsStoreContext);
    if (value === undefined) {
        throw new Error("Missing InstructionsStoreProvider in the tree");
    }
    return value;
};

export const useInstructionsStoreApi = (): InstructionsStore =>
    useInstructionsStoreContext();

export const useInstructionsStore = <T>(
    selector: (state: InstructionsStoreState) => T,
): T => {
    const store = useInstructionsStoreContext();
    return useStore(store, selector);
};

/**
 * Get all actions.
 * Action references are stable, but this hook returns a new object each render.
 * Avoid using the returned object as a prop or effect dependency.
 */
export const useInstructionsActions = (): InstructionsActions => {
    const store = useInstructionsStoreContext();
    const state = store.getState();
    return {
        loadDiskTemplates: state.loadDiskTemplates,
        loadVersions: state.loadVersions,
        loadDeployedVersion: state.loadDeployedVersion,
        loadVersionDetail: state.loadVersionDetail,
        setActivePlatform: state.setActivePlatform,
        setActiveSection: state.setActiveSection,
        setSectionExpanded: state.setSectionExpanded,
        dismissGuide: state.dismissGuide,
        showGuidePanel: state.showGuidePanel,
        setError: state.setError,
        clearError: state.clearError,
        selectTemplate: state.selectTemplate,
        selectVersion: state.selectVersion,
        selectDefault: state.selectDefault,
        requestSelectVersion: state.requestSelectVersion,
        requestSelectDefault: state.requestSelectDefault,
        updateContent: state.updateContent,
        toggleDiff: state.toggleDiff,
        toggleWrapLines: state.toggleWrapLines,
        requestResetTemplate: state.requestResetTemplate,
        resetTemplate: state.resetTemplate,
        setVersionName: state.setVersionName,
        setVersionDescription: state.setVersionDescription,
        createVersion: state.createVersion,
        deployVersion: state.deployVersion,
        undeployVersion: state.undeployVersion,
        requestDeleteVersion: state.requestDeleteVersion,
        deleteVersion: state.deleteVersion,
        closeConfirmDialog: state.closeConfirmDialog,
        confirmAction: state.confirmAction,
        setChatPanelOpen: state.setChatPanelOpen,
        toggleChatPanel: state.toggleChatPanel,
        setTestChatState: state.setTestChatState,
        getBaseContent: state.getBaseContent,
    };
};
