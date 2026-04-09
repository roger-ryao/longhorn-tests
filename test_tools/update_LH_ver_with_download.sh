#!/bin/bash

# Check if the correct number of arguments are provided
if [ "$#" -ne 3 ]; then
    echo ""
    echo "Usage: $0 <old_version> <new_version> <longhorn_version>"
    echo ""
    echo "Arguments:"
    echo "  <old_version>       The version of Longhorn images to be replaced (e.g., v1.10.x-head, v1.11.x-head, master)."
    echo "  <new_version>       The new version of Longhorn images to use (e.g., v1.10.3-dev-20260405, v1.11.2-dev-20260405, master-head)."
    echo "  <longhorn_version>  The branch or tag from which to download the Longhorn YAML file."
    echo ""
    echo "  Examples:"
    echo ""
    echo "    # For downloading longhorn.yaml from the v1.10.x branch"
    echo "    $0 v1.10.x-head v1.10.3-dev-20260405 v1.10.x"
    echo ""
    echo "    # For downloading longhorn.yaml from the v1.11.x branch"
    echo "    $0 v1.11.x-head v1.11.2-dev-20260405 v1.11.x"
    echo ""
    echo "    # For downloading longhorn.yaml from the master branch"
    echo "    $0 master-head v1.12.0-dev-20260405 master"
    echo ""
    exit 1
fi

# Capture the input arguments
OLD_VERSION=$1
NEW_VERSION=$2
LONGHORN_VERSION=$3

# Define the file path for the downloaded longhorn.yaml
FILE_PATH="longhorn.yaml"

# Print the URL to be downloaded
echo "Downloading: https://raw.githubusercontent.com/longhorn/longhorn/${LONGHORN_VERSION}/deploy/longhorn.yaml"

# Download the specified version of the longhorn.yaml file
if ! wget -O "$FILE_PATH" "https://raw.githubusercontent.com/longhorn/longhorn/${LONGHORN_VERSION}/deploy/longhorn.yaml"; then
    echo "Error downloading longhorn.yaml. Please check the Longhorn version."
    exit 1
fi

# Define the list of Longhorn image names
IMAGES=(
    "longhornio/longhorn-ui"
    "longhornio/longhorn-manager"
    "longhornio/longhorn-engine"
    "longhornio/longhorn-instance-manager"
    "longhornio/longhorn-share-manager"
    "longhornio/backing-image-manager"
)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "=========================================================="
echo "Starting image replacements in $FILE_PATH..."
echo "=========================================================="

SUMMARY_OUTPUT=""

# Loop through each image and perform the find/replace
for IMAGE in "${IMAGES[@]}"; do
    SHORT_NAME="${IMAGE##*/}" # e.g. extracts longhorn-engine from longhornio/longhorn-engine
    if "${SCRIPT_DIR}/check_LH_component_images.sh" "${NEW_VERSION}" "${IMAGE}"; then
        echo "✅ [SUCCESS] ${IMAGE}:${NEW_VERSION} is fully built."
        # Use sed to replace old version with new version
        sed -i "s|${IMAGE}:${OLD_VERSION}|${IMAGE}:${NEW_VERSION}|g" "$FILE_PATH"
    elif "${SCRIPT_DIR}/check_LH_component_images.sh" "${NEW_VERSION}-amd64" "${IMAGE}"; then
        echo "⚠️ [PARTIAL] ${IMAGE}:${NEW_VERSION} missing multi-arch, but AMD64 exists."
        sed -i "s|${IMAGE}:${OLD_VERSION}|${IMAGE}:${NEW_VERSION}-amd64|g" "$FILE_PATH"
        SUMMARY_OUTPUT+="\n• ${SHORT_NAME}:${NEW_VERSION} > Use ${SHORT_NAME}:${NEW_VERSION}-amd64 instead"
    elif "${SCRIPT_DIR}/check_LH_component_images.sh" "${NEW_VERSION}-arm64" "${IMAGE}"; then
        echo "⚠️ [PARTIAL] ${IMAGE}:${NEW_VERSION} missing multi-arch, but ARM64 exists."
        sed -i "s|${IMAGE}:${OLD_VERSION}|${IMAGE}:${NEW_VERSION}-arm64|g" "$FILE_PATH"
        SUMMARY_OUTPUT+="\n• ${SHORT_NAME}:${NEW_VERSION} > Use ${SHORT_NAME}:${NEW_VERSION}-arm64 instead"
    else
        echo "⚠️ [SKIPPED] ${IMAGE}:${NEW_VERSION} is NOT built."
        SUMMARY_OUTPUT+="\n• ${SHORT_NAME}:${NEW_VERSION} > Use ${SHORT_NAME}:${OLD_VERSION} instead"
    fi
done

# Define the new filename based on the new version
NEW_FILE_PATH="longhorn-${NEW_VERSION}.yaml"

# Move the modified file to the new file name
mv "$FILE_PATH" "$NEW_FILE_PATH"

echo "=========================================================="
echo "Replacement complete. Updated file saved as $NEW_FILE_PATH."

if [ -n "$SUMMARY_OUTPUT" ]; then
    echo ""
    echo "${NEW_VERSION}"
    echo -e "$SUMMARY_OUTPUT" | sed '/^$/d'
fi
