#!/bin/bash

# Check if the correct number of arguments are provided
if [ "$#" -lt 1 ]; then
    echo ""
    echo "Usage: $0 <longhorn_version> [image_name]"
    echo ""
    echo "  Example:"
    echo "    $0 v1.12.0-dev-20260405"
    echo "    $0 v1.12.0-dev-20260405 longhornio/longhorn-engine"
    echo ""
    exit 1
fi

VERSION=$1
SPECIFIC_IMAGE=$2

if [ -n "$SPECIFIC_IMAGE" ]; then
    IMAGES=("$SPECIFIC_IMAGE")
    # Quiet mode for single image check, no extra output
    QUIET=1
else
    IMAGES=(
        "longhornio/longhorn-ui"
        "longhornio/longhorn-manager"
        "longhornio/longhorn-engine"
        "longhornio/longhorn-instance-manager"
        "longhornio/longhorn-share-manager"
        "longhornio/backing-image-manager"
    )
    QUIET=0
    echo "=========================================================="
    echo "Checking Longhorn images for version: ${VERSION}"
    echo "=========================================================="
fi

MISSING_IMAGES=0
FAILED_LIST=()

for IMAGE in "${IMAGES[@]}"; do
    FULL_IMAGE="${IMAGE}:${VERSION}"
    if [ "$QUIET" -eq 0 ]; then echo "Checking ${FULL_IMAGE} ..."; fi
    
    # Check manifest first. This is much faster than full docker pull
    # and allows us to verify if multi-arch (like arm64) is included.
    MANIFEST=$(docker manifest inspect "${FULL_IMAGE}" 2>/dev/null)
    
    IMAGE_READY=false
    if [ -n "$MANIFEST" ]; then
        if [ "$QUIET" -eq 0 ]; then echo "  ✅ Image exists on registry"; fi
        
        # If the combined image exists on the registry, it is ready.
        # The build process publishes the multi-arch manifest only after both
        # amd64 and arm64 builds complete, so no further arch check is needed.
        IMAGE_READY=true
    else
        # Fallback: if manifest inspect fails (e.g., experimental features not enabled),
        # we try standard docker pull.
        if docker pull -q "${FULL_IMAGE}" >/dev/null 2>&1; then
            if [ "$QUIET" -eq 0 ]; then
                echo "  ✅ FOUND (via pull)"
                echo "  └── ⚠️ Unable to inspect multi-arch manifest. Check Docker experimental features."
            fi
            IMAGE_READY=true
        else
            if [ "$QUIET" -eq 0 ]; then
                echo "  ❌ NOT FOUND or PULL FAILED"
                echo "  └── 🔍 Checking arch-specific tags for diagnosis..."
                for ARCH in amd64 arm64; do
                    ARCH_MANIFEST=$(docker manifest inspect "${IMAGE}:${VERSION}-${ARCH}" 2>/dev/null)
                    if [ -n "$ARCH_MANIFEST" ]; then
                        echo "  └── 🟡 ${IMAGE}:${VERSION}-${ARCH} exists (${ARCH} build done, multi-arch not yet merged)"
                    else
                        echo "  └── 🔴 ${IMAGE}:${VERSION}-${ARCH} not found (${ARCH} build not done)"
                    fi
                done
            fi
        fi
    fi
    
    if [ "$IMAGE_READY" = false ]; then
        MISSING_IMAGES=$((MISSING_IMAGES + 1))
        FAILED_LIST+=("${FULL_IMAGE} (Not fully built)")
    fi
    if [ "$QUIET" -eq 0 ]; then echo ""; fi
done

if [ "$QUIET" -eq 1 ]; then
    if [ "$MISSING_IMAGES" -eq 0 ]; then
        exit 0
    else
        exit 1
    fi
fi

echo "=========================================================="
if [ "$MISSING_IMAGES" -eq 0 ]; then
    echo "🎉 All component images for ${VERSION} are ready!"
    exit 0
else
    echo "❌ Error: Found ${MISSING_IMAGES} issue(s) with images:"
    for failed in "${FAILED_LIST[@]}"; do
        echo "  - $failed"
    done
    exit 1
fi
